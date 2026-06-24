"""Create a real CATCH Trust admin user in the `admin_users` collection.

This gives us a genuine, org-scoped admin to test the multi-tenant login and
settings flows with (the env-fallback admin has no org_id).

Usage:
    cd backend
    python -m scripts.create_catch_admin

Safe to run more than once: it checks whether the username already exists and
skips creation if so.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from firebase_admin import firestore
from werkzeug.security import generate_password_hash
from services.firebase_service import FirebaseService

USERNAME = "ricki.catch"
EMAIL = "ricki@catchtrust.org"
PASSWORD = "CatchAdmin123!"
ORG_ID = "2I8r2Hb2q7pNgjDbcG8w"


def main():
    FirebaseService.initialize()
    db = FirebaseService.get_db()
    if db is None:
        print("ERROR: Could not connect to Firestore. Run "
              "`gcloud auth application-default login` and try again.")
        sys.exit(1)

    # Idempotency: skip if an admin with this username already exists.
    existing = db.collection('admin_users').where('username', '==', USERNAME).limit(1).stream()
    for doc in existing:
        print(f"Admin '{USERNAME}' already exists (id: {doc.id}) — skipping.")
        return

    doc_ref = db.collection('admin_users').document()
    doc_ref.set({
        'first_name': 'Ricki',
        'last_name': 'Van Rensburg',
        'email': EMAIL,
        'username': USERNAME,
        # Hashed with pbkdf2:sha256 to match the login/reset flow in auth.py.
        'password': generate_password_hash(PASSWORD, method='pbkdf2:sha256'),
        'role': 'super_admin',
        'org_id': ORG_ID,
        'is_active': True,
        'created_at': firestore.SERVER_TIMESTAMP,
    })

    print(f"Created admin '{USERNAME}' (id: {doc_ref.id})")
    print(f"  Log in with email: {EMAIL}")


if __name__ == '__main__':
    main()
