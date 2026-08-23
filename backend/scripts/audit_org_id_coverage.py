"""READ-ONLY production audit: org_id coverage across every org-scoped
Firestore collection, ahead of deploying phase2-reconcile.

phase2-reconcile's org-scoped getters (see services/firebase_service.py)
filter every list read by `where('org_id', '==', org_id)`. Any document
missing org_id, or carrying an org_id that doesn't match a real
organisation, becomes invisible to every org's users the moment that code
is deployed. This script counts the damage before that happens.

Collections audited (every collection read by an org-scoped getter in
firebase_service.py, confirmed via get_all_coaches / get_all_participants /
get_all_sessions / get_all_teams / get_all_players / get_all_locations /
get_all_broadcasts / get_all_content / get_all_urls / get_all_reminders /
get_all_admins_by_org — grep-verified against the rest of backend/ to
confirm no other file adds a `where('org_id', ...)` query on a collection
not listed here):
    coaches, participants, sessions, teams, players, locations,
    broadcasts, content, content_urls, reminders, admin_users

Note: content_urls is the actual collection name behind get_all_urls() —
there is no collection literally named "urls".

Safety (mirrors create_catch_trust_location_admins.py / disable_demo_accounts.py):
  - Refuses to run against any project except teko-236ad (checked twice:
    the configured FIREBASE_PROJECT_ID, and the project the SDK actually
    connected to).
  - Structurally read-only: this file contains no .set(), .update(),
    .delete(), or --commit flag anywhere. Every Firestore call below is
    .stream() or .get() on a query.
  - Field-projected reads: collection scans use .select(['org_id']) so
    only the org_id field (plus always-present doc metadata: id,
    createTime) is ever pulled or held in memory — no other document
    content is read.
  - Nothing beyond doc IDs, createTime, and org_id values is ever printed.
  - A short connectivity probe runs first with a hard timeout, so an
    expired ADC token fails fast with a clear message instead of hanging
    (the Python client has been observed to hang ~300s on credential
    failure — reported 4 expiries today as of this writing).

Usage:
    cd backend
    python -m scripts.audit_org_id_coverage
"""
import sys
import os
import concurrent.futures
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import firebase_admin
from services.firebase_service import FirebaseService
from config import Config

TARGET_PROJECT_ID = "teko-236ad"
PROBE_TIMEOUT_S = 20

# (collection name, label used in report)
ORG_SCOPED_COLLECTIONS = [
    ("coaches", "coaches"),
    ("participants", "participants"),
    ("sessions", "sessions"),
    ("teams", "teams"),
    ("players", "players"),
    ("locations", "locations"),
    ("content", "content"),
    ("content_urls", "content_urls (aka 'urls')"),
    ("reminders", "reminders"),
    ("broadcasts", "broadcasts"),
    ("admin_users", "admin_users"),
]


def _run_with_timeout(fn, timeout_s, label):
    """Run fn() in a worker thread; abort fast (rather than hang) if it
    doesn't return within timeout_s. Used only for the initial connectivity
    probe, where a hung ADC token refresh is the known failure mode."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn)
        try:
            return future.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            print(
                f"ERROR: {label} did not respond within {timeout_s}s — treating this as "
                f"an expired/hung ADC token, not a slow query. Run "
                f"`gcloud auth application-default login` and try again."
            )
            sys.exit(1)


def _is_missing(org_id_val):
    return org_id_val is None or org_id_val == ""


def _fmt_time(t):
    return t.isoformat() if t is not None else "<no createTime>"


def audit_collection(db, collection_name, valid_org_ids):
    """Single pass over one collection: total count, missing-org_id docs
    (id + createTime only), and counts per org_id value not in
    valid_org_ids."""
    total = 0
    missing_docs = []  # (doc_id, create_time)
    org_id_counts = {}  # org_id value -> count (present, non-empty values only)

    query = db.collection(collection_name).select(["org_id"])
    for doc in query.stream():
        total += 1
        data = doc.to_dict() or {}
        org_id_val = data.get("org_id")
        if _is_missing(org_id_val):
            missing_docs.append((doc.id, doc.create_time))
        else:
            org_id_counts[org_id_val] = org_id_counts.get(org_id_val, 0) + 1

    invalid_org_id_counts = {
        oid: count for oid, count in org_id_counts.items() if oid not in valid_org_ids
    }

    return {
        "total": total,
        "missing_docs": missing_docs,
        "invalid_org_id_counts": invalid_org_id_counts,
    }


def main():
    configured_project = getattr(Config, "FIREBASE_PROJECT_ID", None)
    print(f"Configured FIREBASE_PROJECT_ID: {configured_project!r}")
    if configured_project != TARGET_PROJECT_ID:
        print(f"ERROR: refusing to run — expected {TARGET_PROJECT_ID!r}, got {configured_project!r}.")
        sys.exit(1)

    print("READ ONLY audit — no writes will be made under any circumstance.\n")

    FirebaseService.initialize()
    db = FirebaseService.get_db()
    if db is None:
        print("ERROR: Could not connect to Firestore. Run `gcloud auth application-default login` and try again.")
        sys.exit(1)

    actual_project = firebase_admin.get_app().project_id
    if actual_project != TARGET_PROJECT_ID:
        print(f"ERROR: refusing to run — Firebase app initialized against {actual_project!r}, not {TARGET_PROJECT_ID!r}.")
        sys.exit(1)
    print(f"Confirmed connected project: {actual_project!r}\n")

    # --- Connectivity probe, hard-timeout guarded ---------------------------
    print(f"Probing connectivity (org list, timeout {PROBE_TIMEOUT_S}s)...")

    def _probe():
        return list(db.collection("organisations").select([]).stream())

    org_docs = _run_with_timeout(_probe, PROBE_TIMEOUT_S, "organisations probe")
    print(f"Probe OK — {len(org_docs)} organisation doc(s) visible.\n")

    # --- Organisations -------------------------------------------------------
    valid_org_ids = {}
    for doc in db.collection("organisations").select(["name"]).stream():
        data = doc.to_dict() or {}
        valid_org_ids[doc.id] = data.get("name")

    print("=" * 70)
    print(f"ORGANISATIONS: {len(valid_org_ids)} total")
    for org_id, name in valid_org_ids.items():
        print(f"  {org_id}  ({name!r})")
    print()

    # --- Per-collection audit -------------------------------------------------
    results = {}
    print("=" * 70)
    print("PER-COLLECTION org_id COVERAGE")
    print(f"{'collection':30s} {'total':>10s} {'missing/null/empty':>20s}")
    for coll_name, label in ORG_SCOPED_COLLECTIONS:
        r = audit_collection(db, coll_name, valid_org_ids)
        results[coll_name] = r
        print(f"{label:30s} {r['total']:>10d} {len(r['missing_docs']):>20d}")
    print()

    # --- Missing org_id detail -------------------------------------------------
    print("=" * 70)
    print("MISSING / NULL / EMPTY org_id — DETAIL (doc IDs + createTime only)")
    any_missing = False
    for coll_name, label in ORG_SCOPED_COLLECTIONS:
        missing = results[coll_name]["missing_docs"]
        if not missing:
            continue
        any_missing = True
        times = [t for _, t in missing if t is not None]
        earliest = min(times) if times else None
        latest = max(times) if times else None
        print(f"\n{label}: {len(missing)} document(s)")
        print(f"  createTime range: {_fmt_time(earliest)}  to  {_fmt_time(latest)}")
        for doc_id, create_time in missing:
            print(f"    {doc_id}  createTime={_fmt_time(create_time)}")
    if not any_missing:
        print("None. No document in any audited collection is missing org_id.")
    print()

    # --- Invalid (unrecognised) org_id detail -----------------------------------
    print("=" * 70)
    print("org_id VALUES NOT MATCHING ANY REAL ORGANISATION")
    any_invalid = False
    for coll_name, label in ORG_SCOPED_COLLECTIONS:
        invalid_counts = results[coll_name]["invalid_org_id_counts"]
        if not invalid_counts:
            continue
        any_invalid = True
        print(f"\n{label}:")
        for org_id_val, count in sorted(invalid_counts.items(), key=lambda kv: -kv[1]):
            print(f"    org_id={org_id_val!r}  count={count}")
    if not any_invalid:
        print("None. Every non-empty org_id found matches a real organisation.")
    print()

    # --- Bottom line -------------------------------------------------------------
    total_missing = sum(len(r["missing_docs"]) for r in results.values())
    total_invalid = sum(sum(r["invalid_org_id_counts"].values()) for r in results.values())
    total_would_vanish = total_missing + total_invalid

    print("=" * 70)
    print("BOTTOM LINE")
    print(f"  Documents with missing/null/empty org_id: {total_missing}")
    print(f"  Documents with org_id not matching any real organisation: {total_invalid}")
    print(f"  TOTAL documents that would become invisible if phase2-reconcile deploys now: {total_would_vanish}")
    print()
    print("Done. No writes were made.")


if __name__ == "__main__":
    main()
