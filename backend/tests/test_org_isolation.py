"""Automated proof of cross-org data isolation.

This is the single most important test in the codebase: it exists to catch
any regression that would let one organisation read another organisation's
data. If anything here fails, treat it as a real gap in the org-isolation
fix (backend/services/firebase_service.py) or in the JWT/route wiring around
it — NOT a test bug. Do not edit these tests to make a failure go away;
report the failure and fix the underlying code, or escalate.

Requires teko-staging-tgh to already be seeded with test-org-a / test-org-b
test data — run `python -m scripts.seed_staging_test_data` first. Tests that
fail with "expected N, got 0" style errors likely mean the seed data isn't
present, not that isolation is broken; check that before concluding
isolation itself has a gap.

Refuses to run against anything other than teko-staging-tgh.

Usage:
    cd backend
    pytest tests/test_org_isolation.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv

STAGING_ENV_PATH = os.path.join(os.path.dirname(__file__), '..', '.env.staging')
EXPECTED_PROJECT_ID = 'teko-staging-tgh'

if not os.path.exists(STAGING_ENV_PATH):
    raise RuntimeError(
        f"{STAGING_ENV_PATH} not found. Create backend/.env.staging before running these tests."
    )

# override=True so this always wins over backend/.env, which config.py's own
# load_dotenv() would otherwise pick up (with override=False, so it can
# never clobber a key already set here). This is what keeps these tests
# pointed at staging even though backend/.env exists in this repo.
load_dotenv(dotenv_path=STAGING_ENV_PATH, override=True)
os.environ['FIREBASE_CREDENTIALS_PATH'] = ''  # force ADC, never a service account key

from config import Config  # noqa: E402

if Config.FIREBASE_PROJECT_ID != EXPECTED_PROJECT_ID:
    raise RuntimeError(
        f"REFUSING TO RUN: FIREBASE_PROJECT_ID resolved to "
        f"'{Config.FIREBASE_PROJECT_ID}', expected '{EXPECTED_PROJECT_ID}'. "
        f"These tests read and must never touch anything but the staging "
        f"project."
    )

import pytest  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from scripts.seed_staging_test_data import _doc_ids  # noqa: E402

ORG_A = 'test-org-a'
ORG_B = 'test-org-b'
IDS_A = _doc_ids(ORG_A)
IDS_B = _doc_ids(ORG_B)


@pytest.fixture(scope='session', autouse=True)
def _firestore_ready():
    """Fail loudly and immediately if we can't reach staging Firestore at all,
    rather than letting every test fail individually with a connection error
    that could be mistaken for an isolation failure."""
    db = FirebaseService.initialize()
    if db is None:
        pytest.exit("Could not connect to Firestore — see logs above.", returncode=1)
    if db.project != EXPECTED_PROJECT_ID:
        pytest.exit(
            f"REFUSING TO RUN: connected Firestore client is on project "
            f"'{db.project}', expected '{EXPECTED_PROJECT_ID}'.",
            returncode=1,
        )
    yield db


def _assert_seed_data_present():
    """Sanity precondition, not an isolation check: confirm the seed script
    has actually run. A test suite that silently 'passes' against empty
    collections proves nothing about isolation."""
    org_a_doc = FirebaseService.get_db().collection('organisations').document(ORG_A).get()
    org_b_doc = FirebaseService.get_db().collection('organisations').document(ORG_B).get()
    if not org_a_doc.exists or not org_b_doc.exists:
        pytest.fail(
            f"Seed data for {ORG_A}/{ORG_B} not found in {EXPECTED_PROJECT_ID}. "
            f"Run `python -m scripts.seed_staging_test_data` first."
        )


# ---------------------------------------------------------------------------
# get_all_* isolation: query as org A, must see only org A, never org B.
# ---------------------------------------------------------------------------

# (label, callable, minimum expected count for org A/B — 0 means the seed
# script does not currently create data for this collection, so the check
# below is vacuously true rather than a strong proof; see the note printed
# for that case.)
GET_ALL_METHODS = [
    ('get_all_coaches', FirebaseService.get_all_coaches, 2),
    ('get_all_sessions', FirebaseService.get_all_sessions, 1),
    ('get_all_players', FirebaseService.get_all_players, 2),
    ('get_all_teams', FirebaseService.get_all_teams, 1),
    ('get_all_locations', FirebaseService.get_all_locations, 0),
    ('get_all_broadcasts', FirebaseService.get_all_broadcasts, 1),
    ('get_all_content', FirebaseService.get_all_content, 1),
    ('get_all_urls', FirebaseService.get_all_urls, 1),
]


@pytest.mark.parametrize('label,method,min_expected', GET_ALL_METHODS, ids=[m[0] for m in GET_ALL_METHODS])
def test_get_all_isolates_by_org(label, method, min_expected):
    _assert_seed_data_present()

    if min_expected == 0:
        print(f"\nNOTE: {label} — no test data seeded for this collection "
              f"(seed_staging_test_data.py does not create locations). This "
              f"check is vacuously true and does not strongly prove isolation "
              f"for {label}; it only proves org B records don't leak into an "
              f"empty result.")

    org_a_records = method(ORG_A)
    org_b_records = method(ORG_B)

    # Precondition: prove the seeded data is actually visible at all, so an
    # empty result below can't be mistaken for successful isolation.
    if min_expected > 0:
        assert len(org_a_records) >= min_expected, (
            f"{label}(org_id={ORG_A!r}) returned {len(org_a_records)} records, "
            f"expected at least {min_expected}. Seed data may be missing — "
            f"run scripts.seed_staging_test_data first."
        )
        assert len(org_b_records) >= min_expected, (
            f"{label}(org_id={ORG_B!r}) returned {len(org_b_records)} records, "
            f"expected at least {min_expected}. Seed data may be missing."
        )

    # The actual isolation check.
    for record in org_a_records:
        assert record.get('org_id') == ORG_A, (
            f"{label}(org_id={ORG_A!r}) returned a record with org_id="
            f"{record.get('org_id')!r} (id={record.get('id')!r}) — expected {ORG_A!r} only."
        )
    for record in org_b_records:
        assert record.get('org_id') == ORG_B, (
            f"{label}(org_id={ORG_B!r}) returned a record with org_id="
            f"{record.get('org_id')!r} (id={record.get('id')!r}) — expected {ORG_B!r} only."
        )

    org_a_ids = {r.get('id') for r in org_a_records}
    org_b_ids = {r.get('id') for r in org_b_records}
    leaked_into_a = org_a_ids & org_b_ids
    assert not leaked_into_a, (
        f"{label}(org_id={ORG_A!r}) leaked {len(leaked_into_a)} record(s) that "
        f"also appear under {ORG_B!r}: {leaked_into_a}"
    )
    # Also confirm none of org A's results are literally one of org B's known
    # seeded document IDs (belt-and-braces against an id/org_id mismatch bug).
    known_org_b_ids = set(IDS_B.values())
    leaked_known_b_ids = org_a_ids & known_org_b_ids
    assert not leaked_known_b_ids, (
        f"{label}(org_id={ORG_A!r}) returned known {ORG_B!r} document id(s): "
        f"{leaked_known_b_ids}"
    )


# ---------------------------------------------------------------------------
# Single-document getters: guessing another org's ID must return None.
# ---------------------------------------------------------------------------

SINGLE_DOC_GETTERS = [
    ('get_coach', FirebaseService.get_coach, 'coach_1'),
    ('get_session', FirebaseService.get_session, 'session'),
    ('get_player', FirebaseService.get_player, 'player_1'),
]


@pytest.mark.parametrize('label,method,doc_key', SINGLE_DOC_GETTERS, ids=[m[0] for m in SINGLE_DOC_GETTERS])
def test_single_doc_getter_blocks_cross_org_id_guess(label, method, doc_key):
    _assert_seed_data_present()
    org_b_doc_id = IDS_B[doc_key]

    # Sanity precondition: the record must actually exist and be fetchable
    # under its OWN org, proving this isn't just "always returns None".
    own_org_result = method(org_b_doc_id, ORG_B)
    assert own_org_result is not None, (
        f"{label}({org_b_doc_id!r}, org_id={ORG_B!r}) returned None for a record "
        f"that should exist — seed data may be missing, run "
        f"scripts.seed_staging_test_data first."
    )
    assert own_org_result.get('org_id') == ORG_B

    # The actual attack: org A guesses org B's document ID.
    cross_org_result = method(org_b_doc_id, ORG_A)
    assert cross_org_result is None, (
        f"{label}({org_b_doc_id!r}, org_id={ORG_A!r}) returned {ORG_B!r}'s record "
        f"instead of None — an org can fetch another org's record by guessing its ID."
    )


# ---------------------------------------------------------------------------
# conversation_service.load_rag_context: RAG knowledge base must be org-scoped.
# ---------------------------------------------------------------------------

def test_load_rag_context_isolates_by_org():
    _assert_seed_data_present()

    context_a = ConversationService.load_rag_context(ORG_A)

    assert context_a, "load_rag_context(test-org-a) returned empty — seed data may be missing."

    # Org A's own content/URL must be present.
    assert 'Org A confidential coaching notes' in context_a, (
        "Org A's content_text was not found in its own RAG context."
    )
    assert 'FAKE test URL resource — Org A' in context_a, (
        "Org A's content_url title was not found in its own RAG context."
    )
    assert 'test-org-a-resource' in context_a, (
        "Org A's content_url link was not found in its own RAG context."
    )

    # Org B's content/URL must never leak into org A's context.
    assert 'Org B confidential coaching notes' not in context_a, (
        "SECURITY: org B's content_text leaked into org A's RAG context."
    )
    assert 'FAKE test URL resource — Org B' not in context_a, (
        "SECURITY: org B's content_url title leaked into org A's RAG context."
    )
    assert 'test-org-b-resource' not in context_a, (
        "SECURITY: org B's content_url link leaked into org A's RAG context."
    )

    # Mirror check the other direction, so a one-sided bug (e.g. a query
    # that only breaks for one specific org_id ordering) can't hide.
    context_b = ConversationService.load_rag_context(ORG_B)
    assert 'Org B confidential coaching notes' in context_b
    assert 'Org A confidential coaching notes' not in context_b, (
        "SECURITY: org A's content_text leaked into org B's RAG context."
    )
