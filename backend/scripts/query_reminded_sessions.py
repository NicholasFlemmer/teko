"""Throwaway, READ-ONLY production analysis script.

Purpose: capture the exact set of sessions at status='reminded' before and
after resuming teko-mark-missed, so the scheduler's first run (with the
mark_missed_sessions fix live) can be verified session-by-session.

This script performs ONLY reads against production Firestore (teko-236ad).
It contains no .set(), .update(), .delete(), or .add() calls anywhere.
It is intentionally NOT committed to git.

Usage:
    cd backend
    FIREBASE_PROJECT_ID=teko-236ad python3 scripts/query_reminded_sessions.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import firebase_admin  # noqa: E402
from firebase_admin import credentials, firestore  # noqa: E402

EXPECTED_PROJECT_ID = 'teko-236ad'


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

    docs = list(db.collection('sessions').where('status', '==', 'reminded').stream())
    print()
    print(f"sessions at status='reminded': {len(docs)}")
    print()
    for doc in docs:
        data = doc.to_dict()
        coach_check_ins = data.get('coach_check_ins') or {}
        check_in_time = data.get('check_in_time')
        print(f"session_id={doc.id} "
              f"date={data.get('date')!r} "
              f"end_time={data.get('end_time')!r} "
              f"start_time={data.get('start_time')!r} "
              f"coach_check_ins_nonempty={bool(coach_check_ins)} "
              f"coach_check_ins_keys={list(coach_check_ins.keys())} "
              f"check_in_time_present={check_in_time is not None}")


if __name__ == '__main__':
    main()
