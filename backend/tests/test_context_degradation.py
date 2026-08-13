"""Unit tests for context-failure handling in ConversationService.

Simulates Firestore query failures via monkeypatch — not a real broken
index — so these tests are fast, deterministic, and never depend on
staging state. Proves the Phase 2 step 3b fix: a query failure inside
load_coach_context/load_rag_context is logged at ERROR level and surfaces
as an explicit note in the assembled context, never as silent empty
context, and never leaks through as a user-facing error reply.

Pure unit tests: FirebaseService's directory reads are stubbed via
monkeypatch, so nothing here touches Firestore — same convention as
test_person_service.py.

This file still loads .env.staging before importing any services module,
even though it never talks to Firestore. Reason: config.py reads
FIREBASE_PROJECT_ID into a class attribute once, at first import, and
never re-reads it — so whichever test file's imports run FIRST in a given
`pytest tests/` session permanently decides Config.FIREBASE_PROJECT_ID for
every other test file in that same session, regardless of any later
load_dotenv(override=True) call. This file happens to sort alphabetically
before the staging-guarded suites (test_conversation_ai_person_agnostic.py,
test_org_isolation.py, test_person_resolution_e2e.py), so without this it
would win that race with the wrong (dev) project id and make those files'
own staging guard fail. Loading the same .env.staging here keeps every
file consistent no matter what order pytest collects them in.

Usage:
    cd backend
    pytest tests/test_context_degradation.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv

STAGING_ENV_PATH = os.path.join(os.path.dirname(__file__), '..', '.env.staging')
if os.path.exists(STAGING_ENV_PATH):
    load_dotenv(dotenv_path=STAGING_ENV_PATH, override=True)
    os.environ['FIREBASE_CREDENTIALS_PATH'] = ''

import pytest  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
from services.gemini_service import GeminiService  # noqa: E402

DEGRADED_MARKER = '[SYSTEM NOTE:'


def _raise(exc):
    return lambda *a, **kw: (_ for _ in ()).throw(exc)


def test_sessions_query_failure_logs_error_and_degrades_context(monkeypatch, caplog):
    """The exact bug this fix addresses: a sessions query failure must not
    silently return empty context, and must not discard a team list that
    already loaded successfully."""
    monkeypatch.setattr(FirebaseService, 'get_all_teams', lambda org_id: [
        {'id': 'team-1', 'name': 'U15s', 'age_group': 'U15', 'coach_ids': ['coach-1']}
    ])
    monkeypatch.setattr(FirebaseService, 'get_all_players', lambda org_id, team_id=None: [])
    monkeypatch.setattr(FirebaseService, 'get_all_sessions',
                         _raise(Exception("400 The query requires an index")))

    with caplog.at_level('ERROR'):
        context = ConversationService.load_coach_context('coach-1', 'org-a')

    assert 'YOUR TEAMS:' in context, "Team data that loaded fine must survive a later sessions failure."
    assert 'U15s' in context
    assert DEGRADED_MARKER in context, "A failed sessions query must produce a visible degradation note."
    assert any(
        r.levelname == 'ERROR' and 'session' in r.message.lower()
        and 'coach-1' in r.message and 'org-a' in r.message
        for r in caplog.records
    ), "Expected an ERROR log identifying the coach_id/org_id for a session-context failure."


def test_teams_query_failure_does_not_discard_working_sessions(monkeypatch, caplog):
    """Mirror of the above: a teams failure must not discard sessions that
    loaded fine, and must itself degrade visibly."""
    monkeypatch.setattr(FirebaseService, 'get_all_teams',
                         _raise(Exception("simulated Firestore error")))
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda *a, **kw: [
        {'id': 'session-1', 'date': '2099-01-01', 'start_time': '10:00', 'type': 'practice', 'status': 'scheduled'}
    ])

    with caplog.at_level('ERROR'):
        context = ConversationService.load_coach_context('coach-1', 'org-a')

    assert 'YOUR UPCOMING SESSIONS:' in context, "Session data that loaded fine must survive a teams failure."
    assert DEGRADED_MARKER in context
    assert any(
        r.levelname == 'ERROR' and 'team' in r.message.lower() and 'coach-1' in r.message
        for r in caplog.records
    ), "Expected an ERROR log identifying the coach_id/org_id for a team-context failure."


def test_rag_content_failure_degrades_without_discarding_urls(monkeypatch, caplog):
    """RAG's content and URL fetches are independent — a content failure
    must not discard URL resources that loaded fine."""
    monkeypatch.setattr(FirebaseService, 'get_all_content',
                         _raise(Exception("simulated Firestore error")))
    monkeypatch.setattr(FirebaseService, 'get_all_urls', lambda org_id: [
        {'title': 'Coaching Guide', 'url': 'https://example.com/guide', 'description': '', 'instructions': ''}
    ])

    with caplog.at_level('ERROR'):
        rag_context = ConversationService.load_rag_context('org-a')

    assert 'Coaching Guide' in rag_context, "URL data that loaded fine must survive a content failure."
    assert DEGRADED_MARKER in rag_context
    assert any(
        r.levelname == 'ERROR' and 'content' in r.message.lower() and 'org-a' in r.message
        for r in caplog.records
    ), "Expected an ERROR log identifying org_id for a RAG content failure."


def test_rag_url_failure_degrades_without_discarding_content(monkeypatch, caplog):
    monkeypatch.setattr(FirebaseService, 'get_all_content', lambda org_id: [
        {'title': 'Drill Library', 'content_text': 'Warm-up drills for beginners.', 'topic': 'Fitness'}
    ])
    monkeypatch.setattr(FirebaseService, 'get_all_urls',
                         _raise(Exception("simulated Firestore error")))

    with caplog.at_level('ERROR'):
        rag_context = ConversationService.load_rag_context('org-a')

    assert 'Drill Library' in rag_context
    assert DEGRADED_MARKER in rag_context
    assert any(r.levelname == 'ERROR' and 'url' in r.message.lower() for r in caplog.records)


def test_context_degradation_does_not_become_user_facing_error(monkeypatch):
    """generate_response must still return a normal, helpful reply — the
    degradation note is a system-level prompt signal, never surfaced as an
    error message to the person messaging."""
    monkeypatch.setattr(FirebaseService, 'get_all_teams',
                         _raise(Exception("simulated Firestore error")))
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda *a, **kw: [])
    monkeypatch.setattr(FirebaseService, 'get_all_content', lambda org_id: [])
    monkeypatch.setattr(FirebaseService, 'get_all_urls', lambda org_id: [])
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: {'id': org_id, 'type': 'sports'})
    monkeypatch.setattr(FirebaseService, 'get_org_terminology',
                         lambda org_id: FirebaseService.DEFAULT_TERMINOLOGY_BY_TYPE['sports'])
    monkeypatch.setattr(ConversationService, 'get_conversation_history', lambda phone, limit=10: [])
    monkeypatch.setattr(ConversationService, 'save_message', lambda phone, role, content: None)

    stubbed_reply = "Here's a great warm-up drill for beginners: light jogging followed by dynamic stretches."
    captured = {}

    def _fake_gemini(prompt):
        captured['prompt'] = prompt
        return stubbed_reply

    monkeypatch.setattr(GeminiService, 'generate_custom_message', _fake_gemini)

    response = ConversationService.generate_response(
        phone='27821234567',
        user_message='What is a good warm-up drill?',
        org_id='org-a',
        person_name='Alice',
        person_id='coach-1',
        person_type='coach',
    )

    assert response == stubbed_reply, "A context failure must not turn into an error reply to the person messaging."
    assert DEGRADED_MARKER in captured['prompt'], "The degradation note must still reach the assembled prompt."


# ---------------------------------------------------------------------------
# Phase 2 step 3c: get_conversation_history degraded the same way its
# siblings did before 3b — logged, but returned [] with no note, which is
# indistinguishable from a genuinely fresh conversation. Same fix, same
# pattern (_context_degraded_note), applied here.
# ---------------------------------------------------------------------------

class _FailingDocRef:
    def collection(self, name):
        return _FailingMessagesCollection()


class _FailingMessagesCollection:
    def order_by(self, *a, **kw):
        return self

    def limit(self, *a, **kw):
        return self

    def stream(self):
        raise Exception("simulated Firestore read failure")


class _FailingConversationsCollection:
    def document(self, key):
        return _FailingDocRef()


class _FailingDb:
    def collection(self, name):
        return _FailingConversationsCollection()


def test_conversation_history_read_failure_returns_degradation_note_not_empty(monkeypatch, caplog):
    monkeypatch.setattr(FirebaseService, 'get_db', lambda: _FailingDb())

    with caplog.at_level('ERROR'):
        history = ConversationService.get_conversation_history('27821234567')

    assert history != [], "A failed read must not look identical to a genuinely empty/fresh conversation."
    assert len(history) == 1
    assert history[0]['role'] == 'system_note'
    assert DEGRADED_MARKER in history[0]['content']
    assert any(
        r.levelname == 'ERROR' and '27821234567' in r.message
        for r in caplog.records
    ), "Expected an ERROR log identifying the phone number for a history-read failure."


def test_conversation_history_failure_note_reaches_assembled_prompt_not_a_chat_turn(monkeypatch):
    """The degradation note must show up as a system-level note in the
    prompt, not be rendered as if the AI ('You:') actually said it."""
    monkeypatch.setattr(FirebaseService, 'get_db', lambda: _FailingDb())
    monkeypatch.setattr(FirebaseService, 'get_all_teams', lambda org_id: [])
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda *a, **kw: [])
    monkeypatch.setattr(FirebaseService, 'get_all_content', lambda org_id: [])
    monkeypatch.setattr(FirebaseService, 'get_all_urls', lambda org_id: [])
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: {'id': org_id, 'type': 'sports'})
    monkeypatch.setattr(FirebaseService, 'get_org_terminology',
                         lambda org_id: FirebaseService.DEFAULT_TERMINOLOGY_BY_TYPE['sports'])
    monkeypatch.setattr(ConversationService, 'save_message', lambda phone, role, content: None)

    stubbed_reply = "Sure, here's a drill."
    captured = {}

    def _fake_gemini(prompt):
        captured['prompt'] = prompt
        return stubbed_reply

    monkeypatch.setattr(GeminiService, 'generate_custom_message', _fake_gemini)

    response = ConversationService.generate_response(
        phone='27821234567',
        user_message='What is a good warm-up drill?',
        org_id='org-a',
        person_name='Alice',
        person_id='coach-1',
        person_type='coach',
    )

    assert response == stubbed_reply, "A history read failure must not turn into an error reply to the person messaging."
    prompt = captured['prompt']
    assert DEGRADED_MARKER in prompt
    assert "Recent conversation history" in prompt
    assert "You: [SYSTEM NOTE:" not in prompt, (
        "The degradation note must not be rendered as though the AI said it in a prior turn."
    )
