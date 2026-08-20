"""Throwaway, READ-ONLY production analysis script.

Purpose: establish the real-world impact of the tzinfo comparison bug that
made get_check_in_info / check_in / add_session_photo_via_token 500 on
every request, prior to revision teko-backend-00044-9pj (2026-08-15).

This script performs ONLY reads against production Firestore (teko-236ad).
It contains no .set(), .update(), .delete(), or .add() calls anywhere.
It is intentionally NOT committed to git -- one-off analysis tool, run
locally against production and then discarded or kept untracked.

Usage:
    cd backend
    FIREBASE_PROJECT_ID=teko-236ad python3 scripts/analyse_check_in_impact.py
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


def describe_value(v):
    return f"{v!r} ({type(v).__name__})"


def print_sample_docs(db, collection_name, n=3):
    """Print raw field names/types for up to n sample docs. No assumptions."""
    docs = list(db.collection(collection_name).limit(n).stream())
    if not docs:
        print(f"Collection '{collection_name}' returned ZERO sample documents.")
        return []
    all_field_names = set()
    for i, doc in enumerate(docs):
        data = doc.to_dict()
        all_field_names.update(data.keys())
        print(f"--- sample doc {i+1}/{len(docs)}: {collection_name}/{doc.id} ---")
        for k, v in data.items():
            print(f"    {k}: {describe_value(v)}")
    print()
    print(f"Union of field names seen across {len(docs)} sample doc(s): {sorted(all_field_names)}")
    return docs


def main():
    # --- Hard project-id gate ---
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

    # ================================================================
    # check_in_tokens
    # ================================================================
    token_docs_sample = []

    def _sample_tokens():
        nonlocal token_docs_sample
        token_docs_sample = print_sample_docs(db, 'check_in_tokens', n=3)

    run_section("SCHEMA: check_in_tokens (sample docs, real field names)", _sample_tokens)

    def _token_count():
        agg = db.collection('check_in_tokens').count()
        result = agg.get()
        total = result[0][0].value
        print(f"check_in_tokens total document count: {total}")

    run_section("1. check_in_tokens: total document count", _token_count)

    # Full single-pass stream over check_in_tokens for: date range, 'used'
    # distribution, and monthly bucket counts. ~1,778 docs -- cheap to
    # stream fully once rather than run separate aggregation queries per
    # question, and it gives an exact (not aggregated/estimated) answer.
    token_rows = []

    def _stream_tokens():
        nonlocal token_rows
        for doc in db.collection('check_in_tokens').stream():
            token_rows.append(doc.to_dict())
        print(f"Streamed {len(token_rows)} check_in_tokens documents for full-pass analysis.")

    run_section("Full-pass stream of check_in_tokens (for sections 2, 3, 4)", _stream_tokens)

    def _date_range():
        if not token_rows:
            print("No token rows streamed -- cannot compute date range.")
            return
        field_candidates = ['created_at']
        present = [f for f in field_candidates if any(f in r for r in token_rows)]
        print(f"Timestamp field(s) actually present on documents: {present}")
        if 'created_at' not in present:
            print("Expected field 'created_at' is ABSENT from every sampled/streamed document.")
            all_keys = set()
            for r in token_rows:
                all_keys.update(r.keys())
            print(f"Fields that DO exist across streamed docs: {sorted(all_keys)}")
            return
        dated = [(r.get('created_at'), r) for r in token_rows if r.get('created_at') is not None]
        missing_count = len(token_rows) - len(dated)
        print(f"Documents with a non-null created_at: {len(dated)}")
        print(f"Documents with created_at missing/null: {missing_count}")
        if dated:
            dated.sort(key=lambda t: t[0])
            earliest_ts, earliest_doc = dated[0]
            latest_ts, latest_doc = dated[-1]
            print(f"Earliest created_at: {earliest_ts.isoformat()}  (token={earliest_doc.get('token')})")
            print(f"Latest created_at:   {latest_ts.isoformat()}  (token={latest_doc.get('token')})")

    run_section("2. check_in_tokens: date range (earliest/latest created_at)", _date_range)

    def _used_distribution():
        if not token_rows:
            print("No token rows streamed -- cannot compute distribution.")
            return
        counter = Counter()
        for r in token_rows:
            if 'used' not in r:
                counter['<field missing entirely>'] += 1
            else:
                v = r['used']
                if v is None:
                    counter['<null>'] += 1
                else:
                    counter[f"{v!r} ({type(v).__name__})"] += 1
        print("Field inspected: 'used'")
        print("Distribution of raw values (including missing/null):")
        for k, v in sorted(counter.items(), key=lambda kv: -kv[1]):
            print(f"    {k}: {v}")
        print(f"Sum (should equal total streamed count {len(token_rows)}): {sum(counter.values())}")

    run_section("3. check_in_tokens: 'used' field distribution", _used_distribution)

    def _monthly_counts():
        if not token_rows:
            print("No token rows streamed -- cannot bucket by month.")
            return
        buckets = Counter()
        no_timestamp = 0
        for r in token_rows:
            ts = r.get('created_at')
            if ts is None:
                no_timestamp += 1
                continue
            key = f"{ts.year:04d}-{ts.month:02d}"
            buckets[key] += 1
        print("Count of check_in_tokens by creation month (YYYY-MM):")
        for month in sorted(buckets.keys()):
            print(f"    {month}: {buckets[month]}")
        print(f"Documents with no created_at (excluded from monthly buckets): {no_timestamp}")

    run_section("4. check_in_tokens: count by month created", _monthly_counts)

    # ================================================================
    # sessions
    # ================================================================
    session_docs_sample = []

    def _sample_sessions():
        nonlocal session_docs_sample
        session_docs_sample = print_sample_docs(db, 'sessions', n=5)

    run_section("SCHEMA: sessions (sample docs, real field names)", _sample_sessions)

    def _session_count():
        agg = db.collection('sessions').count()
        result = agg.get()
        total = result[0][0].value
        print(f"sessions total document count: {total}")

    run_section("5a. sessions: total document count", _session_count)

    # Full stream of sessions, keyed by id, needed for both section 5b
    # (status/attendance distribution) and section 6 (cross-reference
    # against check_in_tokens.session_id).
    sessions_by_id = {}

    def _stream_sessions():
        for doc in db.collection('sessions').stream():
            sessions_by_id[doc.id] = doc.to_dict()
        print(f"Streamed {len(sessions_by_id)} sessions documents.")

    run_section("Full-pass stream of sessions (for sections 5b, 6)", _stream_sessions)

    def _session_status_distribution():
        if not sessions_by_id:
            print("No session rows streamed -- cannot compute distribution.")
            return
        all_keys = set()
        for data in sessions_by_id.values():
            all_keys.update(data.keys())
        candidate_substrings = ['status', 'attend', 'check_in', 'checked', 'present', 'missed']
        candidates = sorted(
            k for k in all_keys
            if any(sub in k.lower() for sub in candidate_substrings)
        )
        print(f"All field names observed across {len(sessions_by_id)} session docs: {sorted(all_keys)}")
        print(f"Field names matching attendance/status-like substrings {candidate_substrings}: {candidates}")
        if not candidates:
            print("No attendance/status-like field names found on sessions documents.")
            return
        for field in candidates:
            counter = Counter()
            for data in sessions_by_id.values():
                if field not in data:
                    counter['<field missing entirely>'] += 1
                else:
                    v = data[field]
                    if v is None:
                        counter['<null>'] += 1
                    elif v == '':
                        counter['<empty string>'] += 1
                    elif isinstance(v, (list, dict)):
                        # summarise container fields rather than dump every value
                        counter[f'<{type(v).__name__}, len={len(v)}>' if len(v) else f'<empty {type(v).__name__}>'] += 1
                    else:
                        counter[f"{v!r} ({type(v).__name__})"] += 1
            print()
            print(f"Distinct values for field '{field}' (including missing/null/empty):")
            for k, v in sorted(counter.items(), key=lambda kv: -kv[1]):
                print(f"    {k}: {v}")

    run_section("5b. sessions: attendance/check-in status field distribution", _session_status_distribution)

    def _cross_reference():
        if not token_rows:
            print("No token rows available -- cannot cross-reference.")
            return
        if not sessions_by_id:
            print("No session rows available -- cannot cross-reference.")
            return
        token_session_ids = set()
        for r in token_rows:
            sid = r.get('session_id')
            if sid:
                token_session_ids.add(sid)
        print(f"Distinct session_id values referenced by check_in_tokens: {len(token_session_ids)}")

        no_record = []
        status_counter = Counter()
        for sid in token_session_ids:
            session = sessions_by_id.get(sid)
            if session is None:
                no_record.append(sid)
                continue
            status = session.get('status', '<no status field>')
            status_counter[f"{status!r}"] += 1

        print(f"Sessions with a check-in token but NO matching sessions/{{id}} document at all: {len(no_record)}")
        if no_record:
            print(f"    (first 10 missing session_ids: {no_record[:10]})")
        print()
        print("Of sessions that DO have a check-in token AND a matching session document,")
        print("breakdown by that session's 'status' field value:")
        for k, v in sorted(status_counter.items(), key=lambda kv: -kv[1]):
            print(f"    status={k}: {v}")

    run_section("6. Cross-reference: sessions with a check-in token vs recorded status", _cross_reference)

    # ================================================================
    # locations
    # ================================================================
    location_docs_sample = []

    def _sample_locations():
        nonlocal location_docs_sample
        location_docs_sample = print_sample_docs(db, 'locations', n=3)

    run_section("SCHEMA: locations (sample docs, real field names)", _sample_locations)

    def _location_gps_counts():
        agg = db.collection('locations').count()
        total = agg.get()[0][0].value
        print(f"locations total document count: {total}")

        all_keys = set()
        docs = list(db.collection('locations').stream())
        for doc in docs:
            all_keys.update(doc.to_dict().keys())
        print(f"All field names observed across {len(docs)} location docs: {sorted(all_keys)}")

        gps_field_candidates = ['latitude', 'longitude', 'lat', 'lng']
        present = [f for f in gps_field_candidates if any(f in doc.to_dict() for doc in docs)]
        print(f"GPS-like field(s) actually present: {present}")

        no_gps = 0
        for doc in docs:
            data = doc.to_dict()
            lat = data.get('latitude')
            lng = data.get('longitude')
            if lat is None or lng is None:
                no_gps += 1
        print(f"locations with latitude and/or longitude missing/null: {no_gps}")
        print(f"locations with both latitude and longitude present (non-null): {len(docs) - no_gps}")

    run_section("7. locations: total count and missing-GPS count", _location_gps_counts)

    banner("DONE")


if __name__ == '__main__':
    main()
