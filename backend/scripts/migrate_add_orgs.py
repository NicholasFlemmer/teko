"""One-time migration: introduce multi-tenancy.

Creates the CATCH Trust organisation in a new `organisations` collection and
backfills `org_id` onto every existing document across the core collections.

Usage:
    cd backend
    python -m scripts.migrate_add_orgs

Safe to run more than once:
  - The CATCH Trust org is matched by its slug; it is reused if it already
    exists rather than duplicated.
  - Documents that already carry an `org_id` are skipped.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from firebase_admin import firestore
from services.firebase_service import FirebaseService

ORG_NAME = "CATCH Trust"
ORG_SLUG = "catch-trust"

# Collections that get an org_id backfilled onto every document.
COLLECTIONS = [
    'coaches',
    'players',
    'teams',
    'locations',
    'sessions',
    'broadcasts',
    'content',
    'reminders',
    'admin_users',
]

TERMINOLOGY = {
    "coach_singular": "Coach",
    "coach_plural": "Coaches",
    "player_singular": "Player",
    "player_plural": "Players",
    "team_singular": "Team",
    "team_plural": "Teams",
    "session_singular": "Session",
    "session_plural": "Sessions",
    "location_singular": "Location",
    "location_plural": "Locations",
}


def get_or_create_org(db):
    """Return the CATCH Trust org ID, creating the org document if needed.

    Idempotent: matches an existing org by slug so re-running does not create
    a duplicate organisation.
    """
    existing = db.collection('organisations').where('slug', '==', ORG_SLUG).limit(1).stream()
    for doc in existing:
        print(f"Organisation '{ORG_NAME}' already exists (id: {doc.id}) — reusing it.")
        return doc.id

    doc_ref = db.collection('organisations').document()
    doc_ref.set({
        'name': ORG_NAME,
        'slug': ORG_SLUG,
        'type': 'ngo',
        'terminology': TERMINOLOGY,
        'created_at': firestore.SERVER_TIMESTAMP,
        'is_active': True,
    })
    print(f"Created organisation '{ORG_NAME}' (id: {doc_ref.id}).")
    return doc_ref.id


def backfill_collection(db, collection_name, org_id):
    """Set org_id on every document in collection_name that doesn't have one."""
    updated = 0
    skipped = 0
    for doc in db.collection(collection_name).stream():
        data = doc.to_dict() or {}
        if data.get('org_id'):
            skipped += 1
            continue
        doc.reference.update({'org_id': org_id})
        updated += 1

    suffix = f" (skipped {skipped} already tagged)" if skipped else ""
    print(f"Updated {updated} {collection_name}{suffix}")
    return updated


def main():
    FirebaseService.initialize()
    db = FirebaseService.get_db()
    if db is None:
        print("ERROR: Could not connect to Firestore. Run "
              "`gcloud auth application-default login` and try again.")
        sys.exit(1)

    print(f"Connected to Firestore project: {db.project}\n")

    org_id = get_or_create_org(db)
    print(f"\nBackfilling org_id={org_id} across {len(COLLECTIONS)} collections...\n")

    total = 0
    for collection_name in COLLECTIONS:
        total += backfill_collection(db, collection_name, org_id)

    print(f"\nDone. Backfilled org_id onto {total} documents across "
          f"{len(COLLECTIONS)} collections.")


if __name__ == '__main__':
    main()
