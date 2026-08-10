"""One-off connection test: verify the local backend can reach the
teko-staging-tgh Firebase project via Application Default Credentials.

Loads backend/.env.staging (not backend/.env), writes one document to a
`_connection_test` collection, reads it back, prints it, then deletes it.

Not a permanent script — safe to delete once the connection is confirmed.

Usage:
    cd backend
    python -m scripts.staging_connection_test
"""
import sys
import os
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')

STAGING_ENV_PATH = os.path.join(os.path.dirname(__file__), '..', '.env.staging')
EXPECTED_PROJECT_ID = 'teko-staging-tgh'


def main():
    if not os.path.exists(STAGING_ENV_PATH):
        print(f"ERROR: {STAGING_ENV_PATH} not found. Create backend/.env.staging first.")
        sys.exit(1)

    # Load staging config with override=True so it wins over anything
    # config.py's own load_dotenv() would otherwise pick up from backend/.env
    # (which is loaded with override=False, so it can never clobber a key we
    # already set here). This is what keeps this script pointed at staging
    # even though backend/.env exists in this repo.
    load_dotenv(dotenv_path=STAGING_ENV_PATH, override=True)

    # Force ADC regardless of what backend/.env sets for this — the whole
    # point of this test is to use `gcloud auth application-default login`
    # with the quota project set to teko-staging-tgh, never a service
    # account key file.
    os.environ['FIREBASE_CREDENTIALS_PATH'] = ''

    from config import Config
    from services.firebase_service import FirebaseService

    project_id = Config.FIREBASE_PROJECT_ID
    print(f"Target Firebase project: {project_id}")
    if project_id != EXPECTED_PROJECT_ID:
        print(
            f"ERROR: expected FIREBASE_PROJECT_ID={EXPECTED_PROJECT_ID}, got "
            f"'{project_id}'. Aborting — refusing to touch a different project."
        )
        sys.exit(1)

    db = FirebaseService.initialize()
    if db is None:
        print("ERROR: Firebase initialization failed — see logs above.")
        sys.exit(1)

    print("Connected to Firestore client.")

    collection = '_connection_test'
    doc_ref = db.collection(collection).document()
    from datetime import datetime, timezone
    test_data = {
        'message': 'phase0-data-isolation staging connection test',
        'created_at': datetime.now(timezone.utc).isoformat(),
    }

    print(f"Writing test document to '{collection}/{doc_ref.id}'...")
    doc_ref.set(test_data)

    print("Reading it back...")
    snapshot = doc_ref.get()
    if not snapshot.exists:
        print("ERROR: document write appeared to succeed but read-back found nothing.")
        sys.exit(1)
    read_data = snapshot.to_dict()
    print(f"Read back: {read_data}")

    print("Deleting test document...")
    doc_ref.delete()

    snapshot_after = doc_ref.get()
    if snapshot_after.exists:
        print("WARNING: document still exists after delete call.")
    else:
        print("Confirmed deleted.")

    print(f"\nSUCCESS: connection to {EXPECTED_PROJECT_ID} Firestore verified end-to-end.")


if __name__ == '__main__':
    main()
