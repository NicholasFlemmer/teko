"""Throwaway, READ-ONLY production analysis script.

Part B / Part A-Q5 follow-on: full detail table for the 54 sessions that
have check_in_location and/or check_in_time recorded but are NOT status
'completed'/'checked_in', plus coach_ids / coach_check_ins detail needed to
confirm (with real data, not just code-reading) whether the multi-coach
partial-check-in + mark-missed race actually explains the location_verified
=True subset.

READ-ONLY. No .set()/.update()/.delete()/.add() Firestore calls anywhere.

Usage:
    cd backend
    FIREBASE_PROJECT_ID=teko-236ad python3 scripts/analyse_54_sessions_detail.py
"""
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import firebase_admin  # noqa: E402
from firebase_admin import credentials, firestore  # noqa: E402

EXPECTED_PROJECT_ID = 'teko-236ad'
SAST = timezone(timedelta(hours=2))


def banner(title):
    print()
    print('=' * 80)
    print(title)
    print('=' * 80)


def run_section(title, fn):
    banner(title)
    try:
        fn()
    except Exception:
        print(f"!!! SECTION FAILED: {title} !!!")
        print(traceback.format_exc())
        print(f"!!! END FAILURE: {title} !!!")


def main():
    project_id = os.environ.get('FIREBASE_PROJECT_ID')
    print(f"FIREBASE_PROJECT_ID in use: {project_id!r}")
    if project_id != EXPECTED_PROJECT_ID:
        print(f"ABORTING: FIREBASE_PROJECT_ID must be exactly {EXPECTED_PROJECT_ID!r}, got {project_id!r}.")
        sys.exit(1)

    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.ApplicationDefault(), {'projectId': project_id})
    db = firestore.client()
    print(f"Connected. firestore client project: {db.project}")
    if db.project != EXPECTED_PROJECT_ID:
        print(f"ABORTING: firestore client bound to {db.project!r}.")
        sys.exit(1)

    sessions = {}

    def _stream():
        for doc in db.collection('sessions').stream():
            sessions[doc.id] = doc.to_dict()
        print(f"Streamed {len(sessions)} sessions documents.")

    run_section("Full-pass stream: sessions", _stream)

    anomalous = []

    def _find_54():
        for sid, s in sessions.items():
            has_evidence = ('check_in_location' in s) or ('check_in_time' in s)
            if has_evidence and s.get('status') not in ('completed', 'checked_in'):
                anomalous.append((sid, s))
        print(f"Sessions matching filter (check-in evidence present, status not completed/checked_in): {len(anomalous)}")

    run_section("Re-derive the 54-session set", _find_54)

    def _table():
        anomalous.sort(key=lambda t: t[1].get('date') or '')
        for sid, s in anomalous:
            coach_ids = s.get('coach_ids') or ([s['coach_id']] if s.get('coach_id') else [])
            coach_check_ins = s.get('coach_check_ins') or {}
            check_in_time = s.get('check_in_time')
            has_loc = 'check_in_location' in s

            # scheduled-window comparison: session date+start/end are naive
            # SAST-local strings (per scheduler_service.py); check_in_time
            # is a UTC-aware Firestore timestamp. Convert session window to
            # UTC-aware for a real before/after comparison.
            window_note = '<cannot compute: missing date/start_time>'
            date_str = s.get('date')
            start_str = s.get('start_time')
            end_str = s.get('end_time')
            if check_in_time and date_str and start_str:
                try:
                    start_naive = datetime.strptime(f"{date_str} {start_str}", "%Y-%m-%d %H:%M")
                    start_utc = start_naive.replace(tzinfo=SAST).astimezone(timezone.utc)
                    if end_str:
                        end_naive = datetime.strptime(f"{date_str} {end_str}", "%Y-%m-%d %H:%M")
                        end_utc = end_naive.replace(tzinfo=SAST).astimezone(timezone.utc)
                    else:
                        end_utc = start_utc + timedelta(hours=2)
                    if check_in_time < start_utc:
                        window_note = f"BEFORE start (start={start_utc.isoformat()})"
                    elif check_in_time > end_utc:
                        window_note = f"AFTER end (end={end_utc.isoformat()})"
                    else:
                        window_note = f"WITHIN window (start={start_utc.isoformat()}, end={end_utc.isoformat()})"
                except ValueError as e:
                    window_note = f"<parse error: {e}>"
            elif not check_in_time:
                window_note = '<no check_in_time on this session>'

            print(f"session_id={sid}")
            print(f"    date={date_str}  start_time={start_str}  end_time={end_str}")
            print(f"    status={s.get('status')!r}")
            print(f"    check_in_time={check_in_time.isoformat() if check_in_time else None}")
            print(f"    check_in_location present={has_loc}")
            print(f"    coach_ids={coach_ids}  (count={len(coach_ids)})")
            print(f"    coach_check_ins present={'coach_check_ins' in s}  entries={len(coach_check_ins)}  keys={list(coach_check_ins.keys())}")
            print(f"    location_verified={s.get('location_verified', '<missing>')!r}")
            print(f"    completed_at={s.get('completed_at').isoformat() if s.get('completed_at') else s.get('completed_at')}")
            print(f"    cancelled_at={s.get('cancelled_at')!r}")
            print(f"    check_in_time vs scheduled window: {window_note}")
            print()

    run_section("Full detail table: all 54 sessions", _table)

    def _race_hypothesis_check():
        """Exhaustive, mutually-exclusive classification of all 54 sessions.
        Every session must land in exactly one bucket -- anything that
        doesn't fit a known mechanism goes in UNCLASSIFIED and is printed
        explicitly rather than silently dropped."""
        bucket_single_false = []      # single/unknown coach, lv=False -> immediate 'missed' (firebase_service.py:294)
        bucket_single_true_anomaly = []  # single/unknown coach, lv=True but NOT checked_in/completed -- unexpected
        bucket_multi_partial = []     # multi-coach, 0 < checked_in < total -> left at 'reminded', later overwritten by mark-missed
        bucket_multi_zero_checkins = []  # multi-coach (coach_ids>1) but coach_check_ins EMPTY/absent despite check_in_location present
        bucket_unclassified = []

        for sid, s in anomalous:
            coach_ids = s.get('coach_ids') or ([s['coach_id']] if s.get('coach_id') else [])
            coach_check_ins = s.get('coach_check_ins') or {}
            n_ids = len(coach_ids)
            n_checked = len(coach_check_ins)
            lv = s.get('location_verified')
            status = s.get('status')

            if n_ids <= 1:
                if lv is False:
                    bucket_single_false.append((sid, lv, status))
                elif lv is True:
                    bucket_single_true_anomaly.append((sid, lv, status, s.get('cancelled_at')))
                else:
                    bucket_unclassified.append((sid, 'single/unknown coach, location_verified missing/other', lv, status))
            else:  # n_ids > 1
                if n_checked == 0:
                    bucket_multi_zero_checkins.append((sid, n_ids, lv, status))
                elif 0 < n_checked < n_ids:
                    bucket_multi_partial.append((sid, n_checked, n_ids, lv, status))
                elif n_checked >= n_ids:
                    bucket_unclassified.append((sid, f'multi-coach with coach_check_ins ({n_checked}) >= coach_ids ({n_ids}) yet not completed/checked_in', lv, status))

        total_classified = (len(bucket_single_false) + len(bucket_single_true_anomaly)
                             + len(bucket_multi_partial) + len(bucket_multi_zero_checkins)
                             + len(bucket_unclassified))
        print(f"Total anomalous sessions: {len(anomalous)}. Classified into buckets: {total_classified} "
              f"(must match — every session lands in exactly one bucket).")

        print()
        print(f"BUCKET A -- single/unknown-coach, location_verified=False: "
              f"immediate status='missed' via firebase_service.py:294 check_in_session logic. Count: {len(bucket_single_false)}")
        for sid, lv, status in bucket_single_false:
            print(f"    {sid}: location_verified={lv!r}, status={status!r}")

        print()
        print(f"BUCKET B -- multi-coach, PARTIAL coach_check_ins (some but not all checked in): "
              f"left at status='reminded' by check_in_session, later overwritten to 'missed' by mark_missed_sessions "
              f"(scheduler_service.py:259) with no check for existing check-in evidence. Count: {len(bucket_multi_partial)}")
        for sid, n_checked, n_total, lv, status in bucket_multi_partial:
            print(f"    {sid}: {n_checked}/{n_total} coaches checked in, top-level location_verified={lv!r}, status={status!r}")

        print()
        print(f"BUCKET C -- multi-coach (coach_ids>1) but coach_check_ins EMPTY despite check_in_location present: "
              f"top-level check_in_location/location_verified were written but no per-coach entry exists -- likely "
              f"predates or bypasses the per-coach coach_check_ins tracking for this session. Count: {len(bucket_multi_zero_checkins)}")
        for sid, n_ids, lv, status in bucket_multi_zero_checkins:
            print(f"    {sid}: coach_ids count={n_ids}, top-level location_verified={lv!r}, status={status!r}")

        print()
        print(f"BUCKET D -- single/unknown-coach, location_verified=True, but status NOT checked_in/completed: "
              f"line 294 should have set status='checked_in' immediately. Anomalous -- needs the cancelled_at/status "
              f"history to explain. Count: {len(bucket_single_true_anomaly)}")
        for sid, lv, status, cancelled_at in bucket_single_true_anomaly:
            print(f"    {sid}: location_verified={lv!r}, status={status!r}, cancelled_at={cancelled_at!r}")

        print()
        print(f"UNCLASSIFIED -- does not fit any of the above mechanisms, flagged rather than guessed. Count: {len(bucket_unclassified)}")
        for sid, reason, lv, status in bucket_unclassified:
            print(f"    {sid}: reason={reason}, location_verified={lv!r}, status={status!r}")

    run_section("Exhaustive classification of all 54 sessions into failure mechanisms", _race_hypothesis_check)

    banner("DONE")


if __name__ == '__main__':
    main()
