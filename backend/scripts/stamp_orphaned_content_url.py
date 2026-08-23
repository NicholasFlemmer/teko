"""One-off fix: stamp org_id onto the single orphaned content_urls document
found by the phase2-reconcile org_id coverage audit.

Target: content_urls/4YuIXacTibv3ic7tOqpg ("ICC Coaching Resources") — the
only document, across every org-scoped collection, that was found missing
org_id AND still matters (a live AI-persona resource link, not test data).
See audit_org_id_coverage.py for the full audit. admin_users/25MrOzOe31IuHKlNMc6N
(a disabled demo account, already inert) is deliberately NOT touched by this
script or any other.

Safety (mirrors create_catch_trust_location_admins.py / disable_demo_accounts.py
/ audit_org_id_coverage.py):
  - Dry run by default. Nothing is written unless you pass --commit.
  - Refuses to run against any project except teko-236ad (checked twice:
    the configured FIREBASE_PROJECT_ID, and the project the SDK actually
    connected to).
  - org_id for "CATCH Trust" is resolved live from the `organisations`
    collection, never hardcoded — cross-checked against the known value
    (2I8r2Hb2q7pNgjDbcG8w) and aborts on a mismatch or on anything other
    than exactly one match.
  - Targets exactly one document by ID. No collection-wide query, no loop
    over anything.
  - Aborts without writing if the document already has a non-empty org_id
    — this script can never overwrite an existing org_id.
  - Writes only the org_id field via .update({'org_id': ...}) — no other
    field is touched.
  - Prints the document's full before and after state.
  - Connectivity probe with a hard 20s timeout up front, so an expired ADC
    token fails fast instead of hanging.

Usage:
    cd backend
    python -m scripts.stamp_orphaned_content_url            # dry run
    python -m scripts.stamp_orphaned_content_url --commit   # actually write
"""
import argparse
import sys
import os
import concurrent.futures
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import firebase_admin
from services.firebase_service import FirebaseService
from config import Config

TARGET_PROJECT_ID = "teko-236ad"
PROBE_TIMEOUT_S = 20

TARGET_COLLECTION = "content_urls"
TARGET_DOC_ID = "4YuIXacTibv3ic7tOqpg"

ORG_NAME = "CATCH Trust"
KNOWN_ORG_ID = "2I8r2Hb2q7pNgjDbcG8w"  # cross-check only, not trusted blindly


def _run_with_timeout(fn, timeout_s, label):
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


def _resolve_org_id(db):
    """Find CATCH Trust's org_id live, verified, not hardcoded."""
    exact = list(db.collection("organisations").where("name", "==", ORG_NAME).limit(2).stream())
    candidates = exact
    if len(candidates) != 1:
        candidates = [
            doc
            for doc in db.collection("organisations").stream()
            if ORG_NAME.lower() in str((doc.to_dict() or {}).get("name", "")).lower()
        ]

    if len(candidates) != 1:
        print(f"ERROR: could not uniquely resolve org_id for {ORG_NAME!r}.")
        if not candidates:
            print("  No organisation matched by exact name or case-insensitive substring.")
        else:
            print("  Multiple candidates found:")
            for doc in candidates:
                print(f"    id={doc.id}  name={(doc.to_dict() or {}).get('name')!r}")
        print("  Resolve manually (check the organisations collection) and re-run.")
        sys.exit(1)

    doc = candidates[0]
    org_id = doc.id
    stored_name = (doc.to_dict() or {}).get("name")
    print(f"Resolved org_id for {ORG_NAME!r}: {org_id}  (stored name: {stored_name!r})")

    if org_id != KNOWN_ORG_ID:
        print(
            f"ERROR: refusing to run — resolved org_id {org_id!r} does not match the "
            f"known value {KNOWN_ORG_ID!r}. Aborting rather than stamping an unexpected org_id."
        )
        sys.exit(1)
    print(f"  Matches known org_id {KNOWN_ORG_ID!r}.")
    return org_id


def _print_doc_state(label, data):
    print(f"  {label}:")
    if data is None:
        print("    <document does not exist>")
        return
    for key in sorted(data.keys()):
        print(f"    {key}: {data[key]!r}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually write to Firestore. Without this flag, only prints what it would do.",
    )
    args = parser.parse_args()

    configured_project = getattr(Config, "FIREBASE_PROJECT_ID", None)
    print(f"Configured FIREBASE_PROJECT_ID: {configured_project!r}")
    if configured_project != TARGET_PROJECT_ID:
        print(f"ERROR: refusing to run — expected {TARGET_PROJECT_ID!r}, got {configured_project!r}.")
        sys.exit(1)

    if not args.commit:
        print("DRY RUN — no writes will be made. Re-run with --commit to actually stamp org_id.\n")

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

    _run_with_timeout(_probe, PROBE_TIMEOUT_S, "organisations probe")
    print("Probe OK.\n")

    org_id = _resolve_org_id(db)
    print()

    # --- Target exactly one document, by ID -----------------------------------
    doc_ref = db.collection(TARGET_COLLECTION).document(TARGET_DOC_ID)
    snapshot = doc_ref.get()

    if not snapshot.exists:
        print(f"ERROR: {TARGET_COLLECTION}/{TARGET_DOC_ID} does not exist. Nothing to stamp.")
        sys.exit(1)

    before = snapshot.to_dict() or {}
    print(f"{TARGET_COLLECTION}/{TARGET_DOC_ID} — BEFORE:")
    _print_doc_state("before", before)
    print()

    existing_org_id = before.get("org_id")
    if existing_org_id not in (None, ""):
        print(
            f"ERROR: document already has a non-empty org_id ({existing_org_id!r}). "
            f"Refusing to overwrite. Aborting without writing."
        )
        sys.exit(1)

    if not args.commit:
        print(f"Would set org_id={org_id!r} on {TARGET_COLLECTION}/{TARGET_DOC_ID}. No other field would change.")
        print("\nDry run only — nothing written. Re-run with --commit to apply.")
        return

    # Scoped update on the exact doc just fetched — org_id only, nothing else.
    doc_ref.update({"org_id": org_id})

    after_snapshot = doc_ref.get()
    after = after_snapshot.to_dict() or {}
    print(f"{TARGET_COLLECTION}/{TARGET_DOC_ID} — AFTER:")
    _print_doc_state("after", after)

    print("\nDone. org_id stamped, no other field changed.")


if __name__ == "__main__":
    main()
