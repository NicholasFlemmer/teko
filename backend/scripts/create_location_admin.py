"""Create a persistent location-admin test account in `admin_users`.

Gives us a real location_admin (scoped to CATCH Trust) to exercise the
role-restricted views without re-inviting each time.

Usage:
    cd backend
    python -m scripts.create_location_admin

Safe to run more than once: it checks whether the email already exists and
skips creation if so.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from firebase_admin import firestore
from werkzeug.security import generate_password_hash
from services.firebase_service import FirebaseService

EMAIL = "lara@catchtrust.org"
USERNAME = "lara.catch"
PASSWORD = "LocationAdmin123!"
ORG_ID = "2I8r2Hb2q7pNgjDbcG8w"


def main():
    FirebaseService.initialize()
    db = FirebaseService.get_db()
    if db is None:
        print("ERROR: Could not connect to Firestore. Run "
              "`gcloud auth application-default login` and try again.")
        sys.exit(1)

    # Idempotency: skip if an admin with this email already exists.
    existing = FirebaseService.get_admin_by_email(EMAIL)
    if existing:
        print(f"Admin '{EMAIL}' already exists (id: {existing['id']}) — skipping.")
        return

    doc_ref = db.collection('admin_users').document()
    doc_ref.set({
        'first_name': 'Lara',
        'last_name': 'Admin',
        'email': EMAIL,
        'username': USERNAME,
        # Hashed with pbkdf2:sha256 to match the login/reset flow in auth.py.
        'password': generate_password_hash(PASSWORD, method='pbkdf2:sha256'),
        'role': 'location_admin',
        'org_id': ORG_ID,
        'is_active': True,
        'created_at': firestore.SERVER_TIMESTAMP,
    })

    print(f"Created location admin '{USERNAME}' (id: {doc_ref.id})")
    print(f"  Log in with email: {EMAIL}")


if __name__ == '__main__':
    main()
