"""End-to-end identity resolution tests: call handle_incoming_message
directly, exactly like the real webhook does, against the REAL seeded
staging phone numbers — no bypassing PersonService.resolve() by passing
org_id/person_id straight into generate_response.

This closes a real coverage gap: the Phase 2 step 2 (test_person_service.py)
and step 3 (test_conversation_ai_person_agnostic.py) suites both passed
while PersonService.resolve() was actually unable to match ANY seeded
staging phone number, because neither suite drove the real entry point
against real seeded data — one used synthetic realistic-format fixtures,
the other called generate_response() directly with identity already
resolved. Only qa_check_person_context.py (which does drive the real
entry point) caught it. These tests exist so that regression can never
hide again.

WhatsAppService.send_message is stubbed (capture, no real send) so this
never attempts to message the fake seeded phone numbers. Nothing else is
stubbed — these probes use /help, which is a canned reply that never
reaches Gemini or writes conversation history, so the full real
ConversationService -> PersonService -> FirebaseService chain runs
untouched.

Requires teko-staging-tgh to already be seeded — run
`python -m scripts.seed_staging_test_data` first, same precondition as
test_org_isolation.py.

Usage:
    cd backend
    pytest tests/test_person_resolution_e2e.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) now lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

import pytest  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
from services.whatsapp_service import WhatsAppService  # noqa: E402
from services.person_service import PersonService  # noqa: E402
from scripts.seed_staging_test_data import _doc_ids  # noqa: E402

# tests/conftest.py already refuses to run this session at all unless
# FIREBASE_PROJECT_ID resolves to this value -- this local copy is only for
# the belt-and-braces check below, which verifies the actually-connected
# Firestore client (not just the environment variable) once initialized.
EXPECTED_PROJECT_ID = 'teko-staging-tgh'

ORG_A = 'test-org-a'
IDS_A = _doc_ids(ORG_A)

UNKNOWN_PHONE = '27000099999'  # SA-shaped but never seeded — matches nobody


@pytest.fixture(scope='session', autouse=True)
def _firestore_ready():
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
    org_a_doc = FirebaseService.get_db().collection('organisations').document(ORG_A).get()
    if not org_a_doc.exists:
        pytest.fail(
            f"Seed data for {ORG_A} not found in {EXPECTED_PROJECT_ID}. "
            f"Run `python -m scripts.seed_staging_test_data` first."
        )


@pytest.fixture(autouse=True)
def _reset_person_cache():
    """PersonService caches phone -> record lookups for 300s. Reset before
    and after every test so seed-data changes are always picked up and one
    test can't leak state into the next."""
    PersonService._coach_cache = {}
    PersonService._participant_cache = {}
    PersonService._cache_ts = 0
    yield
    PersonService._coach_cache = {}
    PersonService._participant_cache = {}
    PersonService._cache_ts = 0


@pytest.fixture
def sent(monkeypatch):
    """Stub WhatsAppService.send_message: capture what would have been
    sent instead of attempting a real send to a fake seeded phone number."""
    box = {}

    def _fake_send(phone_number, message_text, check_in_url=None):
        box['phone_number'] = phone_number
        box['message_text'] = message_text
        return {'success': True}

    monkeypatch.setattr(WhatsAppService, 'send_message', _fake_send)
    return box


def _drive(phone, text, sent_box):
    sent_box.clear()
    ConversationService.clear_pending_attendance(phone)  # defensive reset
    ConversationService.handle_incoming_message(phone, text, message_id='e2e-test')
    return sent_box.get('message_text', '(no message was sent)')


def test_sa_format_number_coach_resolves(sent):
    _assert_seed_data_present()
    coach = FirebaseService.get_coach(IDS_A['coach_1'], ORG_A)
    assert coach and coach['phone_number'] == '27000000101', (
        "Expected test-org-a-coach-1 to be seeded with the SA-shaped phone "
        "'27000000101' — reseed if this fails."
    )

    reply = _drive(coach['phone_number'], '/help', sent)

    assert reply != ConversationService.UNRECOGNISED_SENDER_MESSAGE
    assert '/attendance' in reply, "Expected the coach /help message, which lists /attendance."
    assert 'just ask me anything' not in reply, "Got the participant /help message instead of the coach one."


def test_sa_format_number_participant_resolves(sent):
    _assert_seed_data_present()
    participant = FirebaseService.get_participant(ORG_A, IDS_A['participant_1'])
    assert participant and participant['phone_number'] == '27000000105', (
        "Expected test-org-a-participant-1 to be seeded with the SA-shaped phone "
        "'27000000105' — reseed if this fails."
    )

    reply = _drive(participant['phone_number'], '/help', sent)

    assert reply != ConversationService.UNRECOGNISED_SENDER_MESSAGE
    assert 'just ask me anything' in reply, "Expected the participant /help message."
    assert '/attendance' not in reply, "Got the coach /help message instead of the participant one."


def test_international_format_number_coach_resolves(sent):
    """Regression test for the bug this build fixes: a Brazilian-shaped
    number must resolve a coach, not fall through to the unregistered
    reply. normalize_sa_phone() alone would reject this number outright."""
    _assert_seed_data_present()
    coach = FirebaseService.get_coach(IDS_A['coach_2'], ORG_A)
    assert coach and coach['phone_number'] == '+5511900000102', (
        "Expected test-org-a-coach-2 to be seeded with the Brazilian-shaped phone "
        "'+5511900000102' — reseed if this fails."
    )

    # A real inbound WhatsApp `from` field never has a '+' — simulate that
    # shape here rather than passing the stored value verbatim.
    from_number = coach['phone_number'].lstrip('+')
    reply = _drive(from_number, '/help', sent)

    assert reply != ConversationService.UNRECOGNISED_SENDER_MESSAGE, (
        "International (Brazilian-shaped) coach phone failed to resolve — "
        "identity resolution is incorrectly SA-only."
    )
    assert '/attendance' in reply
    assert 'just ask me anything' not in reply


def test_international_format_number_participant_resolves(sent):
    """Same regression coverage as above, for a participant."""
    _assert_seed_data_present()
    participant = FirebaseService.get_participant(ORG_A, IDS_A['participant_2'])
    assert participant and participant['phone_number'] == '+5511900000106', (
        "Expected test-org-a-participant-2 to be seeded with the Brazilian-shaped phone "
        "'+5511900000106' — reseed if this fails."
    )

    from_number = participant['phone_number'].lstrip('+')
    reply = _drive(from_number, '/help', sent)

    assert reply != ConversationService.UNRECOGNISED_SENDER_MESSAGE, (
        "International (Brazilian-shaped) participant phone failed to resolve — "
        "identity resolution is incorrectly SA-only."
    )
    assert 'just ask me anything' in reply
    assert '/attendance' not in reply


def test_genuinely_unknown_number_gets_unregistered_reply(sent):
    reply = _drive(UNKNOWN_PHONE, 'hello', sent)

    assert reply == ConversationService.UNRECOGNISED_SENDER_MESSAGE
