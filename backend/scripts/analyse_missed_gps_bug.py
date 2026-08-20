"""Throwaway, READ-ONLY production analysis script.

Follow-on to analyse_check_in_impact.py. Purpose: quantify how much of the
41% status='missed' rate on sessions is false-absence caused by the known
bug where a venue with no GPS coordinates makes coach location verification
unresolvable, so the coach gets recorded as missed instead of unverifiable.

READ-ONLY. No .set()/.update()/.delete()/.add() Firestore calls anywhere.

Usage:
    cd backend
    FIREBASE_PROJECT_ID=teko-236ad python3 scripts/analyse_missed_gps_bug.py
"""
import os
import sys
import traceback
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import firebase_admin  # noqa: E402
from firebase_admin import credentials, firestore  # noqa: E402

EXPECTED_PROJECT_ID = 'teko-236ad'


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
        print(f"ABORTING: FIREBASE_PROJECT_ID must be exactly {EXPECTED_PROJECT_ID!r}, "
              f"got {project_id!r}.")
        sys.exit(1)

    if not firebase_admin._apps:
        cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred, {'projectId': project_id})
    db = firestore.client()
    print(f"Connected. firestore client project: {db.project}")
    if db.project != EXPECTED_PROJECT_ID:
        print(f"ABORTING: firestore client is bound to project {db.project!r}.")
        sys.exit(1)

    # ---- full-pass streams (shared across sections) ----
    token_rows = []
    session_rows = {}
    location_rows = {}

    def _stream_all():
        for doc in db.collection('check_in_tokens').stream():
            token_rows.append(doc.to_dict())
        print(f"Streamed {len(token_rows)} check_in_tokens documents.")
        for doc in db.collection('sessions').stream():
            session_rows[doc.id] = doc.to_dict()
        print(f"Streamed {len(session_rows)} sessions documents.")
        for doc in db.collection('locations').stream():
            location_rows[doc.id] = doc.to_dict()
        print(f"Streamed {len(location_rows)} locations documents.")

    run_section("Full-pass stream: check_in_tokens, sessions, locations", _stream_all)

    # sample schema check for fields this script specifically relies on
    def _schema_check():
        expected_token_fields = {'used', 'created_at', 'session_id', 'coach_id'}
        expected_session_fields = {'status', 'check_in_location', 'check_in_time',
                                    'location_id', 'location_verified', 'date'}
        expected_location_fields = {'name', 'org_id', 'address', 'latitude', 'longitude'}

        token_keys = set()
        for r in token_rows[:20]:
            token_keys.update(r.keys())
        session_keys = set()
        for r in list(session_rows.values())[:20]:
            session_keys.update(r.keys())
        location_keys = set()
        for r in list(location_rows.values())[:20]:
            location_keys.update(r.keys())

        print(f"check_in_tokens fields expected by this script: {sorted(expected_token_fields)}")
        print(f"    present: {sorted(expected_token_fields & token_keys)}")
        print(f"    ABSENT:  {sorted(expected_token_fields - token_keys)}")
        print(f"sessions fields expected by this script: {sorted(expected_session_fields)}")
        print(f"    present: {sorted(expected_session_fields & session_keys)}")
        print(f"    ABSENT:  {sorted(expected_session_fields - session_keys)}")
        print(f"locations fields expected by this script: {sorted(expected_location_fields)}")
        print(f"    present: {sorted(expected_location_fields & location_keys)}")
        print(f"    ABSENT:  {sorted(expected_location_fields - location_keys)}")

    run_section("SCHEMA CHECK: confirm expected field names actually exist", _schema_check)

    # ================================================================
    # 1. The 9 used=True tokens
    # ================================================================
    def _used_tokens():
        used = [r for r in token_rows if r.get('used') is True]
        print(f"Tokens with used=True: {len(used)}")
        used.sort(key=lambda r: r.get('created_at'))
        for r in used:
            ca = r.get('created_at')
            print(f"    created_at={ca.isoformat() if ca else None}  "
                  f"session_id={r.get('session_id')}  coach_id={r.get('coach_id')}  "
                  f"token={r.get('token')}")
        months = Counter()
        for r in used:
            ca = r.get('created_at')
            if ca:
                months[f"{ca.year:04d}-{ca.month:02d}"] += 1
        print(f"Month breakdown of used=True tokens: {dict(months)}")
        all_nov_2025 = all(
            r.get('created_at') and r['created_at'].year == 2025 and r['created_at'].month == 11
            for r in used
        )
        print(f"All 9 from November 2025: {all_nov_2025}")

    run_section("1. check_in_tokens where used=True (all)", _used_tokens)

    # ================================================================
    # 2. Sessions with check-in evidence but not completed/checked_in
    # ================================================================
    anomalous_sessions = []

    def _anomalous():
        for sid, s in session_rows.items():
            has_evidence = ('check_in_location' in s) or ('check_in_time' in s)
            if not has_evidence:
                continue
            status = s.get('status')
            if status in ('completed', 'checked_in'):
                continue
            anomalous_sessions.append((sid, s))

        print(f"Sessions with check_in_location or check_in_time present, "
              f"but status NOT IN ('completed','checked_in'): {len(anomalous_sessions)}")
        status_breakdown = Counter(s.get('status', '<no status>') for _, s in anomalous_sessions)
        print("Breakdown by status:")
        for k, v in sorted(status_breakdown.items(), key=lambda kv: -kv[1]):
            print(f"    status={k!r}: {v}")

        print()
        print("Full list:")
        for sid, s in sorted(anomalous_sessions, key=lambda t: t[1].get('date') or ''):
            loc_id = s.get('location_id')
            loc = location_rows.get(loc_id) if loc_id else None
            if loc_id is None:
                gps = '<no location_id on session>'
            elif loc is None:
                gps = f'<location_id {loc_id!r} does not resolve to any locations doc>'
            else:
                has_lat = loc.get('latitude') is not None
                has_lng = loc.get('longitude') is not None
                gps = 'has GPS' if (has_lat and has_lng) else 'MISSING GPS'
            lv = s.get('location_verified', '<missing>')
            print(f"    session_id={sid}  date={s.get('date')}  status={s.get('status')!r}  "
                  f"location_id={loc_id}  location_gps={gps}  location_verified={lv!r}")

    run_section("2. KEY: sessions with check-in evidence but not completed/checked_in", _anomalous)

    # ================================================================
    # 3. Cross-reference all status='missed' sessions against location
    # ================================================================
    missed_sessions = []

    def _missed_by_location():
        nonlocal missed_sessions
        missed_sessions = [(sid, s) for sid, s in session_rows.items() if s.get('status') == 'missed']
        print(f"Total status='missed' sessions: {len(missed_sessions)}")

        no_loc_id = 0
        unresolved_loc_id = 0
        ungeocoded = 0
        geocoded = 0
        ungeocoded_by_location = Counter()
        ungeocoded_location_names = {}

        for sid, s in missed_sessions:
            loc_id = s.get('location_id')
            if not loc_id:
                no_loc_id += 1
                continue
            loc = location_rows.get(loc_id)
            if loc is None:
                unresolved_loc_id += 1
                continue
            has_gps = loc.get('latitude') is not None and loc.get('longitude') is not None
            if has_gps:
                geocoded += 1
            else:
                ungeocoded += 1
                ungeocoded_by_location[loc_id] += 1
                ungeocoded_location_names[loc_id] = loc.get('name', '<no name field>')

        print(f"Missed sessions at a location with NO lat/lng: {ungeocoded}")
        print(f"Missed sessions at a properly geocoded location: {geocoded}")
        print(f"Missed sessions with a location_id that does not resolve to any locations doc: {unresolved_loc_id}")
        print(f"Missed sessions with no location_id at all: {no_loc_id}")
        print(f"Sum check (should equal {len(missed_sessions)}): "
              f"{ungeocoded + geocoded + unresolved_loc_id + no_loc_id}")

        print()
        print("Ungeocoded-venue breakdown (location name -> missed session count):")
        for loc_id, count in sorted(ungeocoded_by_location.items(), key=lambda kv: -kv[1]):
            name = ungeocoded_location_names[loc_id]
            print(f"    {name!r} (location_id={loc_id}): {count} missed sessions")

    run_section("3. Cross-reference: status='missed' sessions vs location GPS", _missed_by_location)

    # ================================================================
    # 4. location_verified distribution across ALL sessions
    # ================================================================
    def _location_verified_distribution():
        counter = Counter()
        for s in session_rows.values():
            if 'location_verified' not in s:
                counter['<field missing entirely>'] += 1
            else:
                v = s['location_verified']
                if v is None:
                    counter['<null>'] += 1
                else:
                    counter[f"{v!r} ({type(v).__name__})"] += 1
        print("Distribution of 'location_verified' across all sessions:")
        for k, v in sorted(counter.items(), key=lambda kv: -kv[1]):
            print(f"    {k}: {v}")
        print(f"Sum (should equal total sessions {len(session_rows)}): {sum(counter.values())}")

    run_section("4. location_verified field distribution (all sessions)", _location_verified_distribution)

    # ================================================================
    # 5. The 6 no-coordinate locations: full detail + total session count
    # ================================================================
    def _no_gps_locations():
        no_gps = {
            lid: loc for lid, loc in location_rows.items()
            if loc.get('latitude') is None or loc.get('longitude') is None
        }
        print(f"Locations with no lat/lng: {len(no_gps)}")

        session_count_by_location = Counter()
        for s in session_rows.values():
            lid = s.get('location_id')
            if lid:
                session_count_by_location[lid] += 1

        for lid, loc in no_gps.items():
            print(f"    location_id={lid}")
            print(f"        name: {loc.get('name')!r}")
            print(f"        org_id: {loc.get('org_id')!r}")
            print(f"        address: {loc.get('address')!r}")
            print(f"        latitude: {loc.get('latitude')!r}  longitude: {loc.get('longitude')!r}")
            print(f"        total sessions at this location (all statuses): {session_count_by_location.get(lid, 0)}")

    run_section("5. The 6 no-coordinate locations: detail + total session traffic", _no_gps_locations)

    # ================================================================
    # 6. Timeline: status='missed' count by month
    # ================================================================
    def _missed_timeline():
        if not missed_sessions:
            print("No missed sessions captured from section 3 -- cannot build timeline.")
            return
        by_month = Counter()
        no_date = 0
        for sid, s in missed_sessions:
            date_str = s.get('date')
            if not date_str or len(date_str) < 7:
                no_date += 1
                continue
            month_key = date_str[:7]  # 'YYYY-MM-DD' -> 'YYYY-MM'
            by_month[month_key] += 1
        print("Field used for timeline: sessions.date (the session's own date, 'YYYY-MM-DD')")
        print("Count of status='missed' sessions by month:")
        for month in sorted(by_month.keys()):
            print(f"    {month}: {by_month[month]}")
        print(f"Missed sessions with no usable date field: {no_date}")

    run_section("6. Timeline: status='missed' sessions by month", _missed_timeline)

    banner("DONE")


if __name__ == '__main__':
    main()
