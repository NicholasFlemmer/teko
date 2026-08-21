"""Disable four demo/QA admin_users accounts on production.

Sets status='disabled' and is_active=False on exactly the four accounts
listed in ACCOUNTS_TO_DISABLE. Does not delete anything — the deployed
login() rejects any status other than 'active' (backend/routes/auth.py),
so this is sufficient to lock them out while leaving any historical
records they're attached to intact.

Safety:
  - Dry run by default. Nothing is written unless you pass --commit.
  - Refuses to run against any project except teko-236ad (checked twice:
    the configured FIREBASE_PROJECT_ID, and the project the SDK actually
    connected to).
  - Only ever touches a doc looked up by an exact email from
    ACCOUNTS_TO_DISABLE via FirebaseService.get_admin_by_email() — no
    collection-wide query, no pattern matching, so nothing outside this
    exact list can be affected.
  - Anything in the list not found in admin_users is skipped and reported,
    never treated as an error that blocks the others.
  - Prints each account's status/is_active before, and again after a
    successful --commit write, so the diff is visible.

Usage:
    cd backend
    python -m scripts.disable_demo_accounts            # dry run
    python -m scripts.disable_demo_accounts --commit   # actually disable
"""
import argparse
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import firebase_admin
from services.firebase_service import FirebaseService
from config import Config

TARGET_PROJECT_ID = "teko-236ad"

ACCOUNTS_TO_DISABLE = [
    "lara@catchtrust.org",
    "ricki+qa1@heytriggr.com",
    "ricki+qa2coach@heytriggr.com",
    "ricki+coach@heytriggr.com",
]


def _describe_status(admin):
    # Mirrors auth.py's own default handling: status defaults to 'active'
    # when the field is absent, so an admin_users doc with no 'status' key
    # is currently a working, loggable-in account.
    status = admin.get("status", "active")
    stored = "status" in admin
    is_active = admin.get("is_active", "<not set>")
    return f"status={status!r} ({'stored' if stored else 'defaulted, not stored'}), is_active={is_active!r}"


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
        print("DRY RUN — no writes will be made. Re-run with --commit to actually disable these accounts.\n")

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

    for raw_email in ACCOUNTS_TO_DISABLE:
        email = raw_email.strip().lower()
        admin = FirebaseService.get_admin_by_email(email)
        if not admin:
            print(f"SKIP: '{email}' not found in admin_users — nothing to disable.\n")
            continue

        print(f"'{email}' (id: {admin['id']})")
        print(f"  before: {_describe_status(admin)}")

        if not args.commit:
            print(f"  would set: status='disabled', is_active=False\n")
            continue

        # Scoped update on the exact doc just looked up by email — never a
        # broad query, never touches anything not in ACCOUNTS_TO_DISABLE.
        doc_ref = db.collection("admin_users").document(admin["id"])
        doc_ref.update({"status": "disabled", "is_active": False})

        after = FirebaseService.get_admin(admin["id"], admin.get("org_id"))
        print(f"  after:  {_describe_status(after) if after else '<could not re-read doc>'}\n")

    print("Done.")


if __name__ == "__main__":
    main()
