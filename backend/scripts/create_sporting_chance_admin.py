"""Create Natalie Pollock's location_admin account for Sporting Chance in `admin_users`.

Same approach as create_catch_trust_location_admins.py: writes directly to
Firestore rather than through POST /api/admin/users, and follows the same
safety pattern as the other create_*.py scripts in this directory.

Safety:
  - Dry run by default. Nothing is written unless you pass --commit.
  - Refuses to run against any project except teko-236ad.
  - org_id for "Sporting Chance" is resolved live from the `organisations`
    collection, never hardcoded.
  - Schema is read from one existing admin_users doc (field names only,
    no values ever printed) rather than assumed.
  - Idempotent: skips (never overwrites) an email that already exists,
    via the same FirebaseService.get_admin_by_email() the deployed login
    code itself uses.
  - Every new doc is a brand-new auto-ID document (db.collection(...).document()
    with no ID argument) -- this script never calls .update() or .set() on an
    existing doc_ref, so there is no code path that can overwrite anything.
  - Password is generated with `secrets` at write time, printed to stdout
    exactly once, and never written to disk or logged.

Usage:
    cd backend
    python -m scripts.create_sporting_chance_admin            # dry run
    python -m scripts.create_sporting_chance_admin --commit   # actually create
"""
import argparse
import string
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import firebase_admin
from firebase_admin import firestore
import secrets as _secrets
from werkzeug.security import generate_password_hash
from services.firebase_service import FirebaseService
from config import Config

TARGET_PROJECT_ID = "teko-236ad"
ORG_NAME = "Sporting Chance"

NEW_ADMINS = [
    {"email": "gm@sportingchance.co.za", "first_name": "Natalie", "last_name": "Pollock"},
]

PASSWORD_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"


def _generate_password(length=20):
    """Cryptographically secure password with guaranteed character diversity."""
    while True:
        pw = "".join(_secrets.choice(PASSWORD_ALPHABET) for _ in range(length))
        if (
            any(c.islower() for c in pw)
            and any(c.isupper() for c in pw)
            and any(c.isdigit() for c in pw)
            and any(c in "!@#$%^&*()-_=+" for c in pw)
        ):
            return pw


def _resolve_org_id(db):
    """Find Sporting Chance's org_id live, verified, not assumed."""
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
    return org_id


def _reference_schema(db):
    """Read one existing admin_users doc's field NAMES only -- never values."""
    docs = list(db.collection("admin_users").limit(1).stream())
    if not docs:
        print(
            "WARNING: admin_users collection appears empty -- cannot confirm schema from "
            "a real document. Falling back to the first_name/last_name/status/is_active "
            "pattern used by the sibling create_*.py scripts."
        )
        return {"first_name", "last_name", "email", "password", "role", "org_id", "is_active", "status", "created_at"}
    keys = set(docs[0].to_dict().keys())
    print(f"Reference admin_users doc field names (values not read or printed): {sorted(keys)}")
    return keys


def _build_fields(email, first_name, last_name, role, org_id, schema_keys, password_hash):
    fields = {
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "password": password_hash,
        "role": role,
        "org_id": org_id,
        # status, not is_active: this is the field auth.py's login() actually
        # gates on (admin.get('status', 'active')).
        "status": "active",
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    if "username" in schema_keys:
        fields["username"] = email.split("@")[0]
    if "is_active" in schema_keys:
        fields["is_active"] = True
    if "updated_at" in schema_keys:
        fields["updated_at"] = firestore.SERVER_TIMESTAMP
    return fields


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
        print("DRY RUN -- no writes will be made. Re-run with --commit to actually create the account.\n")

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

    org_id = _resolve_org_id(db)
    schema_keys = _reference_schema(db)
    print()

    for admin in NEW_ADMINS:
        email = admin["email"].strip().lower()

        existing = FirebaseService.get_admin_by_email(email)
        if existing:
            print(f"SKIP: '{email}' already exists (id: {existing['id']}) -- not touching it.\n")
            continue

        if not args.commit:
            preview = _build_fields(
                email, admin["first_name"], admin["last_name"], "location_admin", org_id, schema_keys,
                password_hash="<generated at write time, not shown in dry run>",
            )
            print(f"Would create admin_users doc for {email}:")
            for k, v in preview.items():
                print(f"    {k}: {v}")
            print()
            continue

        password = _generate_password()
        password_hash = generate_password_hash(password, method="pbkdf2:sha256")
        fields = _build_fields(email, admin["first_name"], admin["last_name"], "location_admin", org_id, schema_keys, password_hash)

        # New auto-ID document only -- never .update()/.set() on an existing
        # doc_ref, so this code path structurally cannot overwrite anything.
        doc_ref = db.collection("admin_users").document()
        doc_ref.set(fields)

        print(f"Created '{email}' (id: {doc_ref.id})")
        print(f"  Password (shown once, not stored anywhere else): {password}\n")

    print("Done.")


if __name__ == "__main__":
    main()
