"""Throwaway, READ-ONLY production snapshot script.

Purpose: before any historical correction for the mark_missed_sessions
overwrite bug, capture a complete, reversible record of every session
that currently shows check-in evidence but is NOT at status='checked_in'
or 'completed' -- the candidate set for correction -- classified into
buckets, with cancelled sessions separately flagged and excluded.

This script performs ONLY reads against production Firestore (teko-236ad)
and a read-only gcloud describe call for the serving revision. It contains
no .set(), .update(), .delete(), or .add() calls anywhere.

The output JSON is written OUTSIDE the repo (~/teko-correction-snapshot-*)
because the repo bdintelligence20/teko is PUBLIC and this data includes
production session and coach IDs. It must never be committed.

Usage:
    cd backend
    FIREBASE_PROJECT_ID=teko-236ad python3 scripts/snapshot_correction_candidates.py
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import firebase_admin  # noqa: E402
from firebase_admin import credentials, firestore  # noqa: E402
from google.cloud.firestore_v1._helpers import DatetimeWithNanoseconds  # noqa: E402

EXPECTED_PROJECT_ID = 'teko-236ad'
OUTPUT_PATH = os.path.expanduser('~/teko-correction-snapshot-2026-08-15.json')

BUCKET_RULES = {
    'A': (
        "single or unknown coach (proxy: <=1 assigned coach via "
        "coach_ids/coach_id), location_verified=False. Marked missed by "
        "the check-in endpoint itself (single/unknown-coach branch: "
        "'checked_in' if location_verified else 'missed'). NOT caused by "
        "the scheduler bug. Left untouched by this fix by deliberate "
        "product decision (pinned, separate open question)."
    ),
    'B': (
        "multi-coach (>1 assigned coach), coach_check_ins non-empty but "
        "does not cover all assigned coach ids (partial check-in). Left "
        "at 'reminded' by check_in_session's pre-fix 'else leave "
        "status as-is' branch, then overwritten to 'missed' by "
        "mark_missed_sessions' pre-fix unconditional overwrite. "
        "THIS IS THE CORRECTION TARGET."
    ),
    'C': (
        "multi-coach (>1 assigned coach), check_in_time present but "
        "coach_check_ins is empty or absent -- pre-March-23 code path "
        "before per-coach check-in tracking existed."
    ),
    'D': (
        "anything with check-in evidence, status not in "
        "(checked_in, completed), that does not match A, B, or C -- "
        "includes anomalies such as multi-coach sessions where "
        "coach_check_ins already covers every assigned coach yet status "
        "was never advanced."
    ),
}

ASSUMPTIONS = (
    "'single or unknown coach' (Bucket A) is approximated from stored "
    "data as len(all_coach_ids) <= 1, using the same coach_ids/coach_id "
    "fallback logic as FirebaseService.get_session_coach_ids. The "
    "runtime-only 'unknown coach' case (a multi-coach session where the "
    "check_in_session coach_id parameter was falsy at call time) cannot "
    "be reconstructed from the stored document alone, since that "
    "parameter is not persisted. Sessions this proxy misclassifies would "
    "fall out as Bucket D rather than being silently folded into B."
)


def get_session_coach_ids(session):
    coach_ids = session.get('coach_ids') or []
    if not coach_ids:
        single = session.get('coach_id')
        if single:
            coach_ids = [single]
    return coach_ids


def json_default(o):
    if isinstance(o, (datetime, DatetimeWithNanoseconds)):
        return o.isoformat()
    return str(o)


def get_serving_revision():
    result = subprocess.run(
        [
            'gcloud', 'run', 'services', 'describe', 'teko-backend',
            '--region=us-central1', f'--project={EXPECTED_PROJECT_ID}',
            '--format=value(status.traffic[0].revisionName)',
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return f"UNKNOWN (gcloud describe failed: {result.stderr.strip()})"
    return result.stdout.strip()


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
        print(f"ABORTING: firestore client is bound to project {db.project!r}, "
              f"not {EXPECTED_PROJECT_ID!r}.")
        sys.exit(1)

    print("Scanning full 'sessions' collection (read-only)...")
    all_docs = list(db.collection('sessions').stream())
    print(f"Total sessions in collection: {len(all_docs)}")

    target = []
    for doc in all_docs:
        data = {'id': doc.id, **doc.to_dict()}
        coach_check_ins = data.get('coach_check_ins') or {}
        check_in_time = data.get('check_in_time')
        status = data.get('status')

        has_evidence = bool(coach_check_ins) or (check_in_time is not None)
        if not has_evidence:
            continue
        if status in ('checked_in', 'completed'):
            continue
        target.append(data)

    print(f"Candidate set (evidence present, status not checked_in/completed): {len(target)}")

    cancelled = []
    buckets = {'A': [], 'B': [], 'C': [], 'D': []}

    for data in target:
        session_id = data['id']
        coach_check_ins = data.get('coach_check_ins') or {}
        check_in_time = data.get('check_in_time')
        location_verified = data.get('location_verified', False)
        status = data.get('status')
        all_coach_ids = get_session_coach_ids(data)
        is_multi_coach = len(all_coach_ids) > 1

        if status == 'cancelled':
            cancelled.append({
                'session_id': session_id,
                'cancelled_at': data.get('cancelled_at'),
                'status': status,
            })

        if not is_multi_coach and location_verified is False:
            bucket = 'A'
        elif is_multi_coach and coach_check_ins and len(coach_check_ins) < len(all_coach_ids):
            bucket = 'B'
        elif is_multi_coach and (check_in_time is not None) and not coach_check_ins:
            bucket = 'C'
        else:
            bucket = 'D'

        buckets[bucket].append({
            'session_id': session_id,
            'status': status,
            'is_multi_coach': is_multi_coach,
            'all_coach_ids': all_coach_ids,
            'coach_check_ins_keys': list(coach_check_ins.keys()),
            'check_in_time_present': check_in_time is not None,
            'location_verified': location_verified,
            'is_cancelled': status == 'cancelled',
        })

    print()
    print("=== Bucket counts ===")
    for b in ('A', 'B', 'C', 'D'):
        print(f"Bucket {b}: {len(buckets[b])}")
    print(f"Cancelled (flagged, excluded from correction): {len(cancelled)}")

    print()
    print("=== Cancelled sessions (excluded from correction) ===")
    if not cancelled:
        print("None.")
    for c in cancelled:
        print(f"  session_id={c['session_id']} cancelled_at={c['cancelled_at']!r}")

    serving_revision = get_serving_revision()
    print()
    print(f"Serving Cloud Run revision: {serving_revision}")

    snapshot = {
        'meta': {
            'snapshot_timestamp_utc': datetime.now(timezone.utc).isoformat(),
            'production_project_id': EXPECTED_PROJECT_ID,
            'serving_cloud_run_revision': serving_revision,
            'bucket_classification_rules': BUCKET_RULES,
            'classification_assumptions': ASSUMPTIONS,
            'candidate_set_definition': (
                "coach_check_ins non-empty OR check_in_time is present, "
                "AND status not in ('checked_in', 'completed')"
            ),
            'total_sessions_scanned': len(all_docs),
            'total_candidate_sessions': len(target),
            'bucket_counts': {b: len(buckets[b]) for b in ('A', 'B', 'C', 'D')},
            'cancelled_flagged_count': len(cancelled),
        },
        'cancelled_flagged': cancelled,
        'bucket_summary': buckets,
        # Complete, unmodified documents for every candidate session, keyed
        # by session id, for full reversibility of any later correction.
        'full_documents': {d['id']: d for d in target},
    }

    with open(OUTPUT_PATH, 'w') as f:
        json.dump(snapshot, f, indent=2, default=json_default)

    print()
    print(f"Snapshot written to: {OUTPUT_PATH}")
    print(f"Absolute path: {os.path.abspath(OUTPUT_PATH)}")


if __name__ == '__main__':
    main()
