"""Create a persistent test coach account in `admin_users`.

Gives us a real coach (scoped to CATCH Trust) to exercise the minimal
coach-only view (Schedule only).

Usage:
    cd backend
    python -m scripts.create_coach

Safe to run more than once: it checks whether the email already exists and
skips creation if so.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from firebase_admin import firestore
from werkzeug.security import generate_password_hash
from services.firebase_service import FirebaseService

EMAIL = "coach@catchtrust.org"
PASSWORD = "CoachTest123!"
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
        print(f"Coach '{EMAIL}' already exists (id: {existing['id']}) — skipping.")
        return

    doc_ref = db.collection('admin_users').document()
    doc_ref.set({
        'first_name': 'Coach',
        'last_name': 'Test',
        'email': EMAIL,
        # Hashed with pbkdf2:sha256 to match the login/reset flow in auth.py.
        'password': generate_password_hash(PASSWORD, method='pbkdf2:sha256'),
        'role': 'coach',
        'org_id': ORG_ID,
        'is_active': True,
        'created_at': firestore.SERVER_TIMESTAMP,
    })

    print(f"Created coach (id: {doc_ref.id})")
    print(f"  Log in with email: {EMAIL}")


if __name__ == '__main__':
    main()
