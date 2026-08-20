"""Tests for the person-agnostic AI conversation path (Phase 2 step 3).

Persona/terminology assertions use the two real seeded staging orgs
(test-org-a = sports, test-org-b = ngo) so the terminology and persona-
prompt plumbing is proven against real Phase 1 org config, not a mock of
it — that's the whole point of this step: layering on top of Phase 1
without silently undoing it.

GeminiService is always stubbed — no real LLM call happens in these tests
(nondeterministic, slow, costs money, and orthogonal to what's being
verified: prompt construction and org/RAG scoping). Conversation history
read/write is also stubbed so these tests never leave throwaway documents
in staging Firestore's `conversations` collection.

Requires teko-staging-tgh to already be seeded — run
`python -m scripts.seed_staging_test_data` first, same precondition as
test_org_isolation.py.

Usage:
    cd backend
    pytest tests/test_conversation_ai_person_agnostic.py -v
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
from services.gemini_service import GeminiService  # noqa: E402
from services.whatsapp_service import WhatsAppService  # noqa: E402

# tests/conftest.py already refuses to run this session at all unless
# FIREBASE_PROJECT_ID resolves to this value -- this local copy is only for
# the belt-and-braces check below, which verifies the actually-connected
# Firestore client (not just the environment variable) once initialized.
EXPECTED_PROJECT_ID = 'teko-staging-tgh'

ORG_A = 'test-org-a'  # sports — coach_singular="Coach", player_singular="Player"
ORG_B = 'test-org-b'  # ngo    — coach_singular="Facilitator", player_singular="Participant"

STUBBED_AI_RESPONSE = "This is a stubbed AI response."


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
    org_b_doc = FirebaseService.get_db().collection('organisations').document(ORG_B).get()
    if not org_a_doc.exists or not org_b_doc.exists:
        pytest.fail(
            f"Seed data for {ORG_A}/{ORG_B} not found in {EXPECTED_PROJECT_ID}. "
            f"Run `python -m scripts.seed_staging_test_data` first."
        )


@pytest.fixture
def captured_prompt(monkeypatch):
    """Stub GeminiService so no real LLM call happens; capture the prompt
    generate_response builds so tests can assert on its contents."""
    captured = {}

    def _fake_generate(prompt):
        captured['prompt'] = prompt
        return STUBBED_AI_RESPONSE

    monkeypatch.setattr(GeminiService, 'generate_custom_message', _fake_generate)
    return captured


@pytest.fixture(autouse=True)
def _stub_conversation_history(monkeypatch):
    """Default to empty history / no-op save so tests never leave throwaway
    documents in staging Firestore's `conversations` collection. Individual
    tests that need specific history content re-patch get_conversation_history
    themselves (the later monkeypatch call wins)."""
    monkeypatch.setattr(ConversationService, 'get_conversation_history',
                         classmethod(lambda cls, phone, limit=10: []))
    monkeypatch.setattr(ConversationService, 'save_message',
                         classmethod(lambda cls, phone, role, content: None))


# ---------------------------------------------------------------------------
# Coach AI path unchanged (sports org — the org type all current production
# orgs use).
# ---------------------------------------------------------------------------

def test_coach_ai_path_unchanged_for_sports_org(captured_prompt, monkeypatch):
    _assert_seed_data_present()
    monkeypatch.setattr(
        ConversationService, 'get_conversation_history',
        classmethod(lambda cls, phone, limit=10: [{'role': 'user', 'content': 'Hi', 'timestamp': None}])
    )

    response = ConversationService.generate_response(
        phone='27000000101',
        user_message='What is a good warm-up drill?',
        org_id=ORG_A,
        person_name='Alice',
        person_id='coach-test-1',
        person_type='coach',
    )

    prompt = captured_prompt['prompt']
    assert response == STUBBED_AI_RESPONSE
    # Sports default persona prompt (Phase 1) still leads, unmodified.
    assert prompt.startswith("You are a professional cricket coaching specialist assistant")
    # The exact original hardcoded wording, byte for byte.
    assert "You are chatting with Coach Alice." in prompt
    assert "Coach: Hi\n" in prompt
    assert "the coach's LATEST message" in prompt
    assert "If the coach switches language" in prompt
    assert "Coach: What is a good warm-up drill?\nYou:" in prompt


# ---------------------------------------------------------------------------
# Participant reaches the AI Q&A fallback (proves the step-2 placeholder is
# gone and the participant isn't stuck on a decline message).
# ---------------------------------------------------------------------------

def test_participant_reaches_ai_qa_and_gets_response(captured_prompt, monkeypatch):
    _assert_seed_data_present()
    sent = {}

    def _fake_send(phone_number, message_text):
        sent['phone_number'] = phone_number
        sent['message_text'] = message_text
        return {'success': True}

    monkeypatch.setattr(WhatsAppService, 'send_message', _fake_send)

    person = {'id': 'participant-test-1', 'org_id': ORG_A, 'name': 'Bongani', 'person_type': 'participant'}
    ConversationService._handle_participant_message('27000000102', 'What is a good warm-up drill?', person)

    assert 'prompt' in captured_prompt, "Gemini was never called — participant did not reach the AI Q&A fallback."
    assert sent.get('message_text') == STUBBED_AI_RESPONSE


# ---------------------------------------------------------------------------
# Persona address line + history labels reflect person_type AND org
# terminology, for both a sports org and an ngo org.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('org_id,person_type,expected_role_word', [
    (ORG_A, 'coach', 'Coach'),
    (ORG_A, 'participant', 'Player'),
    (ORG_B, 'coach', 'Facilitator'),
    (ORG_B, 'participant', 'Participant'),
], ids=['sports-coach', 'sports-participant', 'ngo-coach', 'ngo-participant'])
def test_persona_and_history_reflect_person_type_and_org_terminology(
    org_id, person_type, expected_role_word, captured_prompt, monkeypatch
):
    _assert_seed_data_present()
    monkeypatch.setattr(
        ConversationService, 'get_conversation_history',
        classmethod(lambda cls, phone, limit=10: [{'role': 'user', 'content': 'Hello', 'timestamp': None}])
    )

    ConversationService.generate_response(
        phone='27000000200',
        user_message='Test message',
        org_id=org_id,
        person_name='Test Person',
        person_id='person-test-1',
        person_type=person_type,
    )

    prompt = captured_prompt['prompt']
    assert f"You are chatting with {expected_role_word} Test Person." in prompt
    assert f"{expected_role_word}: Hello\n" in prompt
    assert f"{expected_role_word}: Test message\nYou:" in prompt

    # A participant must never be addressed as "Coach", and an NGO coach
    # must never be addressed as "Coach" either — direct proof of the
    # requirement, not just an artifact of the role_word substitution above.
    if expected_role_word != 'Coach':
        assert "You are chatting with Coach " not in prompt


# ---------------------------------------------------------------------------
# Org-configured ai_persona_prompt override still wins — composition, not
# replacement, and holds for both person types.
# ---------------------------------------------------------------------------

def test_org_configured_persona_prompt_override_wins_for_both_person_types(captured_prompt, monkeypatch):
    custom_prompt = "CUSTOM PERSONA: You are a bespoke assistant for Acme Org. Follow these exact instructions only."

    # Only get_organisation is stubbed — get_ai_persona_prompt and
    # get_org_terminology both call it internally, so this exercises their
    # real priority/fallback logic rather than mocking around it.
    monkeypatch.setattr(FirebaseService, 'get_organisation',
                         lambda org_id: {'id': org_id, 'type': 'sports', 'ai_persona_prompt': custom_prompt})

    for person_type in ('coach', 'participant'):
        response = ConversationService.generate_response(
            phone='27000000300',
            user_message='hi',
            org_id='fake-org-with-override',
            person_name='Zola',
            person_id='p1',
            person_type=person_type,
        )
        assert response == STUBBED_AI_RESPONSE
        prompt = captured_prompt['prompt']
        assert prompt.startswith(custom_prompt), (
            f"Expected the org's ai_persona_prompt override to lead the prompt for "
            f"person_type={person_type!r}, but it didn't."
        )
        # None of the built-in default persona prompts leaked in alongside it.
        assert "EXPERTISE:" not in prompt


# ---------------------------------------------------------------------------
# RAG org isolation holds for participants, not just coaches — the
# highest-value invariant in the codebase, proven through the full
# generate_response pipeline rather than just the underlying function.
# ---------------------------------------------------------------------------

def test_rag_org_isolation_holds_for_participants(captured_prompt, monkeypatch):
    _assert_seed_data_present()

    ConversationService.generate_response(
        phone='27000000400',
        user_message='Tell me about our program',
        org_id=ORG_A,
        person_name='Bongani',
        person_id='participant-test-2',
        person_type='participant',
    )
    prompt_a = captured_prompt['prompt']
    assert 'Org A confidential coaching notes' in prompt_a, (
        "Org A's own RAG content should be visible to an Org A participant."
    )
    assert 'Org B confidential coaching notes' not in prompt_a, (
        "SECURITY: Org B's RAG content leaked into an Org A participant's prompt."
    )

    # Mirror check the other direction.
    ConversationService.generate_response(
        phone='27000000401',
        user_message='Tell me about our program',
        org_id=ORG_B,
        person_name='Thandi',
        person_id='participant-test-3',
        person_type='participant',
    )
    prompt_b = captured_prompt['prompt']
    assert 'Org B confidential coaching notes' in prompt_b
    assert 'Org A confidential coaching notes' not in prompt_b, (
        "SECURITY: Org A's RAG content leaked into an Org B participant's prompt."
    )
