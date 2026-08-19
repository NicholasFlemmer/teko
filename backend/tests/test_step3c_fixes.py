"""Unit tests for Phase 2 step 3c: the silent-swallow cluster fixed after
the step 3b audit (items 2, 4, 5 — see PersonService's own test file for
item 1, and test_context_degradation.py for item 6).

Pure unit tests: Firestore reads are stubbed via monkeypatch (either
FirebaseService's directory methods, or a fake failing db client for the
raw get_db()-based methods), so nothing here touches real infrastructure —
same convention as test_person_service.py and test_context_degradation.py.

Usage:
    cd backend
    pytest tests/test_step3c_fixes.py -v
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
from services.conversation_service import ConversationService, PendingStateReadError  # noqa: E402
from services.person_service import PersonService  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
from services.whatsapp_service import WhatsAppService  # noqa: E402


class _RaisingDocRef:
    def get(self):
        raise Exception("simulated Firestore read failure")

    def delete(self):
        pass


class _RaisingCollection:
    def document(self, key):
        return _RaisingDocRef()


class _RaisingDb:
    def collection(self, name):
        return _RaisingCollection()


@pytest.fixture(autouse=True)
def _reset_person_cache():
    PersonService._coach_cache = {}
    PersonService._participant_cache = {}
    PersonService._cache_ts = 0
    PersonService._cache_populated = False
    yield
    PersonService._coach_cache = {}
    PersonService._participant_cache = {}
    PersonService._cache_ts = 0
    PersonService._cache_populated = False


# ---------------------------------------------------------------------------
# Item 2: the duplicate ConversationService coach cache is gone entirely —
# PersonService is the only identity-resolution cache left.
# ---------------------------------------------------------------------------

def test_duplicate_coach_cache_and_lookup_are_gone():
    assert not hasattr(ConversationService, 'get_coach_by_phone')
    assert not hasattr(ConversationService, '_refresh_coach_cache_if_stale')
    assert not hasattr(ConversationService, '_coach_phone_cache')
    assert not hasattr(ConversationService, '_coach_phone_cache_ts')


def test_attendance_sse_dashboard_name_now_resolved_via_person_service(monkeypatch):
    """handle_attendance_response's SSE 'attendance' event coach_name used
    to come from the now-deleted ConversationService.get_coach_by_phone.
    It must resolve via PersonService now, and gracefully degrade to
    'Unknown' (not raise, not block the already-saved attendance) if
    PersonService can't resolve it."""
    monkeypatch.setattr(FirebaseService, 'update_session', lambda session_id, data: None)
    # Avoid a real Firestore delete() call from clear_pending_attendance —
    # irrelevant to what this test is verifying (the SSE coach_name source).
    monkeypatch.setattr(ConversationService, 'clear_pending_attendance', classmethod(lambda cls, phone: None))
    # handle_attendance_response looks up the session by id (unscoped,
    # org_id=None) twice: once to resolve org_id for the SSE event, once
    # further down for team_id when queuing the pending photo state.
    # Stub it so this stays a pure unit test rather than an implicit real
    # Firestore call.
    monkeypatch.setattr(FirebaseService, 'get_session',
                         lambda session_id, org_id: {'id': session_id, 'org_id': 'org-a', 'team_id': 'team-1'})

    # conversation_service.py does `from routes.sse import push_event`, which
    # binds its own reference at import time — patching routes.sse.push_event
    # would not affect it, so patch conversation_service's own binding.
    captured_events = []
    import services.conversation_service as cs_module
    monkeypatch.setattr(cs_module, 'push_event',
                         lambda event_type, org_id=None, coach_name=None, preview=None, extra=None:
                             captured_events.append({'type': event_type, 'coach_name': coach_name}))

    monkeypatch.setattr(FirebaseService, 'get_all_coaches', lambda org_id: [
        {'id': 'coach-1', 'org_id': 'org-a', 'name': 'Alice', 'phone_number': '0821234567'},
    ])
    monkeypatch.setattr(FirebaseService, 'get_all_participants', lambda org_id: [])

    pending = {
        'players': [{'id': 'p1', 'name': 'Player One', 'number': 1}],
        'session_id': 'session-1',
    }
    ConversationService.handle_attendance_response('27821234567', 'all', pending)

    assert len(captured_events) == 1
    assert captured_events[0]['type'] == 'attendance'
    assert captured_events[0]['coach_name'] == 'Alice', (
        "Expected the SSE event's coach_name to come from PersonService.resolve, not a stale/duplicate cache."
    )


def test_attendance_sse_dashboard_name_falls_back_to_unknown_on_cache_unavailable(monkeypatch):
    """A never-populated PersonService cache must degrade this purely
    cosmetic dashboard label to 'Unknown' rather than raising and blocking
    an attendance confirmation that has already been saved."""
    monkeypatch.setattr(FirebaseService, 'update_session', lambda session_id, data: None)
    monkeypatch.setattr(ConversationService, 'clear_pending_attendance', classmethod(lambda cls, phone: None))
    # See test_attendance_sse_dashboard_name_now_resolved_via_person_service
    # for why this is stubbed: handle_attendance_response looks up the
    # session by id (unscoped, org_id=None) to resolve org_id for the SSE
    # event and, further down, team_id for the pending photo state.
    monkeypatch.setattr(FirebaseService, 'get_session',
                         lambda session_id, org_id: {'id': session_id, 'org_id': 'org-a', 'team_id': 'team-1'})

    captured_events = []
    import services.conversation_service as cs_module
    monkeypatch.setattr(cs_module, 'push_event',
                         lambda event_type, org_id=None, coach_name=None, preview=None, extra=None:
                             captured_events.append({'type': event_type, 'coach_name': coach_name}))

    monkeypatch.setattr(FirebaseService, 'get_all_coaches', lambda org_id: (_ for _ in ()).throw(Exception("down")))
    monkeypatch.setattr(FirebaseService, 'get_all_participants', lambda org_id: (_ for _ in ()).throw(Exception("down")))

    pending = {
        'players': [{'id': 'p1', 'name': 'Player One', 'number': 1}],
        'session_id': 'session-1',
    }
    response = ConversationService.handle_attendance_response('27821234567', 'all', pending)

    assert '✅' in response, "Attendance must still be recorded even though the display-name lookup failed."
    assert captured_events[0]['coach_name'] == 'Unknown'


# ---------------------------------------------------------------------------
# Items 4 & 5: get_pending_attendance / get_pending_photo must raise on a
# read failure, distinguishable from the None "no pending request" case.
# ---------------------------------------------------------------------------

def test_get_pending_attendance_raises_on_read_failure(monkeypatch, caplog):
    monkeypatch.setattr(FirebaseService, 'get_db', lambda: _RaisingDb())

    with caplog.at_level('ERROR'):
        with pytest.raises(PendingStateReadError):
            ConversationService.get_pending_attendance('27821234567')

    assert any(
        r.levelname == 'ERROR' and 'pending attendance' in r.message.lower() and '27821234567' in r.message
        for r in caplog.records
    )


def test_get_pending_photo_raises_on_read_failure(monkeypatch, caplog):
    monkeypatch.setattr(FirebaseService, 'get_db', lambda: _RaisingDb())

    with caplog.at_level('ERROR'):
        with pytest.raises(PendingStateReadError):
            ConversationService.get_pending_photo('27821234567')

    assert any(
        r.levelname == 'ERROR' and 'pending photo' in r.message.lower() and '27821234567' in r.message
        for r in caplog.records
    )


def test_pending_attendance_read_failure_does_not_misroute_into_ai_chat(monkeypatch):
    """The bug this closes: a numeric attendance reply ('2 5 8') falling
    through a swallowed pending-attendance read failure used to look
    exactly like 'no pending request' and get sent to the AI chat instead
    — silently losing the coach's attendance submission. Now the read
    failure must propagate to the existing catch-all, produce the generic
    retry message, and never reach generate_response/Gemini."""
    monkeypatch.setattr(FirebaseService, 'get_all_coaches', lambda org_id: [
        {'id': 'coach-1', 'org_id': 'org-a', 'name': 'Alice', 'phone_number': '0821234567'},
    ])
    monkeypatch.setattr(FirebaseService, 'get_all_participants', lambda org_id: [])
    monkeypatch.setattr(ConversationService, 'get_pending_attendance',
                         classmethod(lambda cls, phone: (_ for _ in ()).throw(PendingStateReadError("down"))))

    ai_called = {'value': False}
    monkeypatch.setattr(ConversationService, 'generate_response',
                         classmethod(lambda cls, **kw: ai_called.__setitem__('value', True) or "AI reply"))

    sent = {}
    monkeypatch.setattr(WhatsAppService, 'send_message',
                         lambda phone_number, message_text: sent.update(phone_number=phone_number, message_text=message_text) or {'success': True})

    ConversationService.handle_incoming_message('27821234567', '2 5 8', message_id='test-1')

    assert not ai_called['value'], "A pending-attendance read failure must never fall through to the AI chat."
    assert sent.get('message_text') == "Sorry, I encountered an error. Please try again."


def test_pending_photo_read_failure_does_not_lose_the_photo_silently(monkeypatch):
    """Mirror of the attendance case for handle_image_message: a failed
    pending-photo read must not be treated as 'no pending photo' (which
    would tell the coach to run /attendance first, discarding their
    photo) — it must surface as a retry-me error instead."""
    monkeypatch.setattr(FirebaseService, 'get_all_coaches', lambda org_id: [
        {'id': 'coach-1', 'org_id': 'org-a', 'name': 'Alice', 'phone_number': '0821234567'},
    ])
    monkeypatch.setattr(FirebaseService, 'get_all_participants', lambda org_id: [])
    monkeypatch.setattr(ConversationService, 'get_pending_photo',
                         classmethod(lambda cls, phone: (_ for _ in ()).throw(PendingStateReadError("down"))))

    sent = {}
    monkeypatch.setattr(WhatsAppService, 'send_message',
                         lambda phone_number, message_text: sent.update(phone_number=phone_number, message_text=message_text) or {'success': True})

    ConversationService.handle_image_message('27821234567', {'id': 'media-1'}, message_id='test-2')

    assert sent.get('message_text') == "Sorry, something went wrong saving your photo. Please try again. 📸"
    assert "run /attendance" not in (sent.get('message_text') or ''), (
        "Must not tell the coach there's no pending photo — that would discard their photo on a transient read failure."
    )
