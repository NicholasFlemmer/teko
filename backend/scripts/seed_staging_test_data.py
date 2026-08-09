"""One-off script: seed two fake organisations into teko-staging-tgh for
manual and automated org-isolation testing.

Creates test-org-a and test-org-b, each with:
  - 1 admin user (role location_admin)
  - 2 coaches, each with a distinct phone number
  - 1 team (both coaches assigned)
  - 2 players on that team
  - 1 session
  - 1 broadcast
  - 1 content item and 1 content_url item (for RAG/knowledge-base checks)

All data is obviously fake and clearly labeled — test-org-* document IDs,
"Test Org A" / "Test Org B" names, +1000000000x phone numbers, *@test.invalid
emails (a reserved TLD that can never resolve) — so it can never be confused
with real client data.

Idempotent: every document uses a deterministic ID derived from the org id
(e.g. test-org-a-coach-1). Re-running deletes each org's existing test
documents by their known IDs and recreates them fresh, so repeated runs
never leave duplicates behind.

Refuses to run against anything other than the teko-staging-tgh project.

Usage:
    cd backend
    python -m scripts.seed_staging_test_data
"""
import sys
import os
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')

STAGING_ENV_PATH = os.path.join(os.path.dirname(__file__), '..', '.env.staging')
EXPECTED_PROJECT_ID = 'teko-staging-tgh'

# --- Test org definitions -------------------------------------------------
# Everything here is obviously fake: test-org-* ids, "Test Org" names,
# +1000000000x phone numbers, *@test.invalid emails.
ORGS = [
    {
        'org_id': 'test-org-a',
        'org_name': 'Test Org A',
        'label': 'Org A',
        'phones': ('+10000000001', '+10000000003'),
    },
    {
        'org_id': 'test-org-b',
        'org_name': 'Test Org B',
        'label': 'Org B',
        'phones': ('+10000000002', '+10000000004'),
    },
]

# Maps each logical record to the Firestore collection it lives in.
_COLLECTION_FOR = {
    'org': 'organisations',
    'admin': 'admin_users',
    'coach_1': 'coaches',
    'coach_2': 'coaches',
    'team': 'teams',
    'player_1': 'players',
    'player_2': 'players',
    'session': 'sessions',
    'broadcast': 'broadcasts',
    'content': 'content',
    'content_url': 'content_urls',
}


def _doc_ids(org_id):
    """Deterministic document IDs for one org's full set of seeded records."""
    return {key: (org_id if key == 'org' else f'{org_id}-{key.replace("_", "-")}')
            for key in _COLLECTION_FOR}


def _delete_existing(db, org_id):
    """Delete any previously-seeded documents for this org, by known ID."""
    deleted = 0
    for key, doc_id in _doc_ids(org_id).items():
        ref = db.collection(_COLLECTION_FOR[key]).document(doc_id)
        if ref.get().exists:
            ref.delete()
            deleted += 1
    return deleted


def _seed_org(db, org_cfg):
    from firebase_admin import firestore
    from werkzeug.security import generate_password_hash

    org_id = org_cfg['org_id']
    label = org_cfg['label']
    ids = _doc_ids(org_id)
    phone_1, phone_2 = org_cfg['phones']
    now = firestore.SERVER_TIMESTAMP

    org_ref = db.collection('organisations').document(org_id)
    already_existed = org_ref.get().exists

    if already_existed:
        print(f"[{label}] Existing test data found for '{org_id}' — deleting before re-seeding...")
        deleted = _delete_existing(db, org_id)
        print(f"[{label}] Deleted {deleted} existing document(s).")
    else:
        print(f"[{label}] No existing test data found for '{org_id}' — creating fresh.")

    created = []

    # Organisation
    org_ref.set({
        'name': org_cfg['org_name'],
        'slug': org_id,
        'type': 'test',
        'is_active': True,
        'created_at': now,
    })
    created.append(('organisations', ids['org']))

    # Admin user (location_admin)
    db.collection('admin_users').document(ids['admin']).set({
        'name': f"{label} Admin",
        'email': f'{org_id}-admin@test.invalid',
        # pbkdf2, not werkzeug's scrypt default, so hashing works on builds
        # without OpenSSL's scrypt (see routes/auth.py's reset_password).
        'password': generate_password_hash('TestPassword123!', method='pbkdf2:sha256'),
        'role': 'location_admin',
        'status': 'active',
        'org_id': org_id,
        'created_at': now,
    })
    created.append(('admin_users', ids['admin']))

    # Coaches
    coach_names = [(ids['coach_1'], f"{label} Coach One", phone_1),
                   (ids['coach_2'], f"{label} Coach Two", phone_2)]
    coach_doc_ids = []
    for doc_id, full_name, phone in coach_names:
        db.collection('coaches').document(doc_id).set({
            'name': full_name,
            'first_name': full_name.rsplit(' ', 2)[0],
            'last_name': ' '.join(full_name.rsplit(' ', 2)[1:]),
            'email': f'{doc_id}@test.invalid',
            'phone_number': phone,
            'org_id': org_id,
            'created_at': now,
        })
        created.append(('coaches', doc_id))
        coach_doc_ids.append(doc_id)

    # Team (both coaches assigned)
    db.collection('teams').document(ids['team']).set({
        'name': f"{label} Team",
        'age_group': 'U15',
        'location_id': '',
        'coach_ids': coach_doc_ids,
        'org_id': org_id,
        'created_at': now,
    })
    created.append(('teams', ids['team']))

    # Players (on that team)
    player_names = [(ids['player_1'], f"{label} Player One", 'PLR-TESTA1' if org_id == 'test-org-a' else 'PLR-TESTB1'),
                     (ids['player_2'], f"{label} Player Two", 'PLR-TESTA2' if org_id == 'test-org-a' else 'PLR-TESTB2')]
    for doc_id, full_name, player_id in player_names:
        first, last = full_name.rsplit(' ', 2)[0], ' '.join(full_name.rsplit(' ', 2)[1:])
        db.collection('players').document(doc_id).set({
            'first_name': first,
            'last_name': last,
            'player_id': player_id,
            'date_of_birth': '2012-01-01',
            'guardian_name': f"{label} Guardian",
            'guardian_email': f'{doc_id}-guardian@test.invalid',
            'guardian_primary_phone': phone_1,
            'guardian_secondary_phone': '',
            'special_notes': 'FAKE TEST DATA — isolation testing only.',
            'team_ids': [ids['team']],
            'org_id': org_id,
            'created_at': now,
        })
        created.append(('players', doc_id))

    # Session
    db.collection('sessions').document(ids['session']).set({
        'date': '2026-12-31',
        'start_time': '10:00',
        'end_time': '11:00',
        'coach_ids': coach_doc_ids,
        'coach_id': coach_doc_ids[0],
        'team_ids': [ids['team']],
        'team_id': ids['team'],
        'address': f'FAKE test address, {label}',
        'status': 'scheduled',
        'type': 'practice',
        'notes': 'FAKE TEST DATA — isolation testing only.',
        'org_id': org_id,
        'created_at': now,
    })
    created.append(('sessions', ids['session']))

    # Broadcast
    db.collection('broadcasts').document(ids['broadcast']).set({
        'channel': 'whatsapp',
        'subject': f'FAKE test broadcast — {label}',
        'message': f'This is a fake test broadcast for isolation testing ({label}).',
        'template_name': '',
        'recipient_ids': coach_doc_ids,
        'sent_by': 'seed_staging_test_data.py',
        'send_results': [],
        'failed_count': 0,
        'estimated_cost': {
            'cost_usd': 0, 'cost_zar': 0, 'message_type': 'service',
            'rate_per_message_usd': 0, 'successful_count': 0,
        },
        'org_id': org_id,
        'created_at': now,
    })
    created.append(('broadcasts', ids['broadcast']))

    # Content item (for RAG check)
    db.collection('content').document(ids['content']).set({
        'title': f'FAKE test content — {label}',
        'type': 'article',
        'topic': 'Isolation Testing',
        'language': 'English',
        'content_text': (
            f'FAKE TEST DATA — {label} confidential coaching notes. '
            f'If a coach from the other test org can see this, data isolation is broken.'
        ),
        'file_name': '',
        'file_url': '',
        'file_path': '',
        'org_id': org_id,
        'created_at': now,
    })
    created.append(('content', ids['content']))

    # Content URL item (for RAG check)
    db.collection('content_urls').document(ids['content_url']).set({
        'url': f'https://test.invalid/{org_id}-resource',
        'title': f'FAKE test URL resource — {label}',
        'description': f'FAKE TEST DATA for isolation testing ({label}).',
        'instructions': 'Do not use — test data only.',
        'org_id': org_id,
        'created_at': now,
    })
    created.append(('content_urls', ids['content_url']))

    return created


def _verify_org(db, org_cfg):
    """Query each collection by org_id and confirm the expected counts."""
    org_id = org_cfg['org_id']
    expected = {
        'admin_users': 1, 'coaches': 2, 'teams': 1, 'players': 2,
        'sessions': 1, 'broadcasts': 1, 'content': 1, 'content_urls': 1,
    }
    print(f"  Verifying org_id='{org_id}' counts:")
    all_ok = True
    for collection, expected_count in expected.items():
        docs = list(db.collection(collection).where('org_id', '==', org_id).stream())
        actual_count = len(docs)
        ok = actual_count == expected_count
        all_ok = all_ok and ok
        status = 'OK' if ok else 'MISMATCH'
        print(f"    {collection:15s} expected={expected_count} actual={actual_count} [{status}]")
    return all_ok


def main():
    if not os.path.exists(STAGING_ENV_PATH):
        print(f"ERROR: {STAGING_ENV_PATH} not found. Create backend/.env.staging first.")
        sys.exit(1)

    # override=True so this always wins over backend/.env, which config.py's
    # own load_dotenv() would otherwise pick up (with override=False, so it
    # can never clobber a key already set here).
    load_dotenv(dotenv_path=STAGING_ENV_PATH, override=True)

    # Force ADC regardless of what backend/.env sets for this.
    os.environ['FIREBASE_CREDENTIALS_PATH'] = ''

    from config import Config
    from services.firebase_service import FirebaseService

    project_id = Config.FIREBASE_PROJECT_ID
    print(f"Target Firebase project: {project_id}")
    if project_id != EXPECTED_PROJECT_ID:
        print(
            f"ERROR: expected FIREBASE_PROJECT_ID={EXPECTED_PROJECT_ID}, got "
            f"'{project_id}'. Aborting — refusing to seed test data into a different project."
        )
        sys.exit(1)

    db = FirebaseService.initialize()
    if db is None:
        print("ERROR: Firebase initialization failed — see logs above.")
        sys.exit(1)

    print("Connected to Firestore client.\n")

    all_created = []
    for org_cfg in ORGS:
        created = _seed_org(db, org_cfg)
        all_created.extend(created)
        print(f"[{org_cfg['label']}] Seeded {len(created)} document(s):")
        for collection, doc_id in created:
            print(f"    {collection}/{doc_id}")
        print()

    print("Verifying final state (should match on every re-run)...")
    all_ok = True
    for org_cfg in ORGS:
        all_ok = _verify_org(db, org_cfg) and all_ok

    print()
    if all_ok:
        print(f"SUCCESS: seeded {len(all_created)} document(s) across {len(ORGS)} test orgs "
              f"in {EXPECTED_PROJECT_ID}, all counts verified.")
    else:
        print("WARNING: one or more collections did not match the expected count — see above.")
        sys.exit(1)


if __name__ == '__main__':
    main()
