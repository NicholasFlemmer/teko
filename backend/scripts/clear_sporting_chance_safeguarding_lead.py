"""Clear the interim safeguarding_lead_name/safeguarding_lead_email fields on
the Sporting Chance organisation document.

works_with_minors is deliberately left untouched -- this script never reads
or writes that field's value.

Once cleared, services/safeguarding_service.py's alert routing (see
_resolve_safeguarding_recipient) falls back to every active location_admin
account on the org, since org.safeguarding_lead_email is the sole recipient
only when set. This is the only place either field is read anywhere in the
deployed backend (confirmed by grep across routes/*.py and services/*.py
before writing this script).

Safety:
  - Dry run by default. Nothing is written unless you pass --commit.
  - Refuses to run against any project except teko-236ad.
  - org_id for "Sporting Chance" is resolved live from the `organisations`
    collection, never hardcoded.
  - Prints the current values of both fields before doing anything, dry run
    or not, so there is a record of what was there.
  - Only ever touches safeguarding_lead_name and safeguarding_lead_email via
    a scoped .update() call -- no other field on the org document is read
    for writing or touched.
  - Snapshots the org document's full pre-write state to a JSON file outside
    the repo (in /tmp) before the write, in --commit mode.

Usage:
    cd backend
    python -m scripts.clear_sporting_chance_safeguarding_lead            # dry run
    python -m scripts.clear_sporting_chance_safeguarding_lead --commit   # actually clear
"""
import argparse
import json
import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import firebase_admin
from services.firebase_service import FirebaseService
from config import Config

TARGET_PROJECT_ID = "teko-236ad"
ORG_NAME = "Sporting Chance"
SNAPSHOT_DIR = "/tmp/teko-snapshots"


def _resolve_org(db):
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
        sys.exit(1)

    doc = candidates[0]
    org_id = doc.id
    data = doc.to_dict() or {}
    print(f"Resolved org_id for {ORG_NAME!r}: {org_id}  (stored name: {data.get('name')!r})")
    return org_id, data


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
        print(f"ERROR: refusing to run -- expected {TARGET_PROJECT_ID!r}, got {configured_project!r}.")
        sys.exit(1)

    if not args.commit:
        print("DRY RUN -- no writes will be made. Re-run with --commit to actually clear the fields.\n")

    FirebaseService.initialize()
    db = FirebaseService.get_db()
    if db is None:
        print("ERROR: Could not connect to Firestore. Run `gcloud auth application-default login` and try again.")
        sys.exit(1)

    actual_project = firebase_admin.get_app().project_id
    if actual_project != TARGET_PROJECT_ID:
        print(f"ERROR: refusing to run -- Firebase app initialized against {actual_project!r}, not {TARGET_PROJECT_ID!r}.")
        sys.exit(1)
    print(f"Confirmed connected project: {actual_project!r}\n")

    org_id, org_data = _resolve_org(db)

    current_name = org_data.get("safeguarding_lead_name")
    current_email = org_data.get("safeguarding_lead_email")
    current_minors = org_data.get("works_with_minors")

    print("\nCurrent values (record of what was there before clearing):")
    print(f"  safeguarding_lead_name:  {current_name!r}")
    print(f"  safeguarding_lead_email: {current_email!r}")
    print(f"  works_with_minors (left untouched): {current_minors!r}")

    if current_name is None and current_email is None:
        print("\nBoth fields are already null -- nothing to do.")
        return

    if not args.commit:
        print("\nWould update organisations/{} with:".format(org_id))
        print("    safeguarding_lead_name: None")
        print("    safeguarding_lead_email: None")
        print("\nDry run only -- nothing written. Re-run with --commit to apply.")
        return

    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    snapshot_path = os.path.join(
        SNAPSHOT_DIR, f"sporting_chance_org_{org_id}_pre_safeguarding_clear_{int(time.time())}.json"
    )
    with open(snapshot_path, "w") as f:
        json.dump({"id": org_id, **{k: (v if not hasattr(v, 'isoformat') else v.isoformat()) for k, v in org_data.items()}}, f, indent=2, default=str)
    print(f"\nSnapshot of full pre-write org document saved to: {snapshot_path}")

    db.collection("organisations").document(org_id).update({
        "safeguarding_lead_name": None,
        "safeguarding_lead_email": None,
    })
    print(f"\nCleared safeguarding_lead_name and safeguarding_lead_email on organisations/{org_id}.")
    print("works_with_minors was not read or written by this script.")


if __name__ == "__main__":
    main()
