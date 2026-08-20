"""Regression tests for scheduler_service.py reading another org's coach or
location because a lookup used org_id=None instead of the org_id already
sitting on the session it was working with.

check_and_send_reminders() runs across every org by design (it starts from
FirebaseService.get_sessions_for_reminder(), which has no org filter at
all) -- that part is intentionally global and untouched here. But once a
specific session is in hand, its location and its coaches must be looked
up scoped to *that session's own org_id*, not read unscoped. Same for
send_end_session_prompts()'s coach lookup.

These tests exercise the real FirebaseService.get_location/get_coach
filtering logic (via a fake Firestore db), not a mock that assumes the
filter works -- so a cross-org document really does have to come back
None for these tests to pass.

Usage:
    cd backend
    pytest tests/test_scheduler_org_scoping.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime, timedelta  # noqa: E402

from services.firebase_service import FirebaseService  # noqa: E402
from services.scheduler_service import SchedulerService, SAST  # noqa: E402
from services.whatsapp_service import WhatsAppService  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402


# ---------------------------------------------------------------------------
# Fake Firestore: real enough for FirebaseService.get_location/get_coach's
# own org-comparison logic to actually run, unlike a mock that just returns
# a canned value.
# ---------------------------------------------------------------------------

class _FakeSnapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class _FakeDocRef:
    def __init__(self, doc_id, data, updates_log=None):
        self._doc_id = doc_id
        self._data = data
        self._updates_log = updates_log

    def get(self):
        return _FakeSnapshot(self._doc_id, self._data)

    def update(self, data):
        if self._updates_log is not None:
            self._updates_log.append((self._doc_id, data))


class _FakeCollection:
    def __init__(self, docs_by_id=None, stream_docs=None, updates_log=None):
        self._docs_by_id = docs_by_id or {}
        self._stream_docs = stream_docs or []
        self._updates_log = updates_log

    def document(self, doc_id):
        return _FakeDocRef(doc_id, self._docs_by_id.get(doc_id), self._updates_log)

    def where(self, *args, **kwargs):
        return self

    def stream(self):
        return iter(self._stream_docs)


class _FakeDb:
    """collections: {name: {'docs_by_id': {...}, 'stream_docs': [...]}}"""

    def __init__(self, collections):
        self._collections = collections
        self.updates = []

    def collection(self, name):
        spec = self._collections.get(name, {})
        return _FakeCollection(spec.get('docs_by_id'), spec.get('stream_docs'), self.updates)


# ---------------------------------------------------------------------------
# check_and_send_reminders -- location lookup (scheduler_service.py, was
# get_location(location_id, None)) and coach lookup (was
# get_coach(coach_id, None)), both now scoped to session.get('org_id').
# ---------------------------------------------------------------------------

def _due_session(session_id='sess-1', org_id='org-a', location_id='loc-1', coach_id='coach-1'):
    """A session whose reminder window is open right now.

    The scheduler's window is 0 <= time_diff <= REMINDER_MINUTES_BEFORE + 1
    (see check_and_send_reminders). Derive the offset from that same config
    value -- halfway into the window -- so this fixture stays valid however
    REMINDER_MINUTES_BEFORE is configured, instead of hardcoding a number
    that can silently drift out of range.
    """
    from config import Config
    when = datetime.now(SAST).replace(tzinfo=None) + timedelta(minutes=Config.REMINDER_MINUTES_BEFORE / 2)
    return {
        'id': session_id,
        'org_id': org_id,
        'status': 'scheduled',
        'date': when.strftime('%Y-%m-%d'),
        'start_time': when.strftime('%H:%M'),
        'location_id': location_id,
        'coach_id': coach_id,
        'coach_ids': [coach_id],
    }


def _run_reminder_job(monkeypatch, session, locations_by_id, coaches_by_id):
    fake_db = _FakeDb({
        'locations': {'docs_by_id': locations_by_id},
        'coaches': {'docs_by_id': coaches_by_id},
    })
    monkeypatch.setattr(FirebaseService, 'get_db', lambda: fake_db)
    monkeypatch.setattr(FirebaseService, 'get_sessions_for_reminder', lambda target: [dict(session)])
    monkeypatch.setattr(FirebaseService, 'create_check_in_token', lambda *a, **kw: None)
    monkeypatch.setattr(ConversationService, 'save_message', lambda *a, **kw: None)

    sent_calls = []

    def _fake_send_check_in_reminder(**kwargs):
        sent_calls.append(kwargs)
        return {'success': True, 'rendered_text': 'reminder sent'}

    monkeypatch.setattr(WhatsAppService, 'send_check_in_reminder', _fake_send_check_in_reminder)

    result = SchedulerService.check_and_send_reminders()
    return result, sent_calls


def test_reminder_location_lookup_passes_session_org_id_and_uses_matching_location(monkeypatch):
    session = _due_session(org_id='org-a', location_id='loc-1', coach_id='coach-1')
    result, sent_calls = _run_reminder_job(
        monkeypatch,
        session,
        locations_by_id={'loc-1': {'org_id': 'org-a', 'name': 'Venue A', 'latitude': -33.9, 'longitude': 18.4}},
        coaches_by_id={'coach-1': {'org_id': 'org-a', 'name': 'Coach A', 'phone_number': '0821234567'}},
    )

    assert result['success'] is True
    assert result['reminders_sent'] == 1
    assert len(sent_calls) == 1
    assert 'Venue A' in sent_calls[0]['location_address']


def test_reminder_location_lookup_does_not_return_a_location_from_another_org(monkeypatch):
    session = _due_session(org_id='org-a', location_id='loc-1', coach_id='coach-1')
    result, sent_calls = _run_reminder_job(
        monkeypatch,
        session,
        locations_by_id={'loc-1': {'org_id': 'org-b', 'name': 'Venue B (other org)', 'latitude': -1.0, 'longitude': 1.0}},
        coaches_by_id={'coach-1': {'org_id': 'org-a', 'name': 'Coach A', 'phone_number': '0821234567'}},
    )

    assert result['success'] is True
    # Reminder still goes out (coach matches) -- but the other org's venue
    # must never surface; get_location(location_id, 'org-a') must return
    # None for a location tagged org-b, falling back to the bare session
    # address/'TBC' instead.
    assert result['reminders_sent'] == 1
    assert len(sent_calls) == 1
    assert 'Venue B' not in sent_calls[0]['location_address']
    assert sent_calls[0]['location_address'] == 'TBC'


def test_reminder_coach_lookup_passes_session_org_id_and_sends_to_matching_coach(monkeypatch):
    session = _due_session(org_id='org-a', location_id='loc-1', coach_id='coach-1')
    result, sent_calls = _run_reminder_job(
        monkeypatch,
        session,
        locations_by_id={'loc-1': {'org_id': 'org-a', 'name': 'Venue A', 'latitude': -33.9, 'longitude': 18.4}},
        coaches_by_id={'coach-1': {'org_id': 'org-a', 'name': 'Coach A', 'phone_number': '0821234567'}},
    )

    assert result['success'] is True
    assert result['reminders_sent'] == 1
    assert result['errors'] == []
    assert len(sent_calls) == 1
    assert sent_calls[0]['coach_name'] == 'Coach A'


def test_reminder_coach_lookup_does_not_return_a_coach_from_another_org(monkeypatch):
    session = _due_session(org_id='org-a', location_id='loc-1', coach_id='coach-1')
    result, sent_calls = _run_reminder_job(
        monkeypatch,
        session,
        locations_by_id={'loc-1': {'org_id': 'org-a', 'name': 'Venue A', 'latitude': -33.9, 'longitude': 18.4}},
        coaches_by_id={'coach-1': {'org_id': 'org-b', 'name': 'Coach B (other org)', 'phone_number': '0821234567'}},
    )

    assert result['success'] is True
    # get_coach(coach_id, 'org-a') must return None for a coach tagged
    # org-b -- no reminder sent, and the coach is reported not found rather
    # than silently reminded through another org's record.
    assert result['reminders_sent'] == 0
    assert len(sent_calls) == 0
    assert any('not found' in e for e in result['errors'])


# ---------------------------------------------------------------------------
# send_end_session_prompts -- coach lookup (scheduler_service.py, was
# get_coach(coach_id, None)), now scoped to the local session_org_id.
# ---------------------------------------------------------------------------

def _ended_session_needing_prompt(session_id='sess-2', org_id='org-a', coach_id='coach-9'):
    """A 'checked_in' session whose end-prompt window is open, and isn't
    stale enough to be skipped."""
    from config import Config
    now = datetime.now(SAST).replace(tzinfo=None)
    end = now - timedelta(minutes=Config.END_SESSION_PROMPT_MINUTES + 5)
    start = end - timedelta(hours=1)
    return {
        'id': session_id,
        'org_id': org_id,
        'status': 'checked_in',
        'date': end.strftime('%Y-%m-%d'),
        'start_time': start.strftime('%H:%M'),
        'end_time': end.strftime('%H:%M'),
        'coach_ids': [coach_id],
        'coach_id': coach_id,
    }


def _run_end_session_prompts_job(monkeypatch, session, coaches_by_id):
    stream_doc = _FakeSnapshot(session['id'], {k: v for k, v in session.items() if k != 'id'})
    fake_db = _FakeDb({
        'sessions': {'stream_docs': [stream_doc]},
        'coaches': {'docs_by_id': coaches_by_id},
    })
    monkeypatch.setattr(FirebaseService, 'get_db', lambda: fake_db)
    monkeypatch.setattr(ConversationService, 'save_message', lambda *a, **kw: None)

    sent_calls = []

    def _fake_send_message(**kwargs):
        sent_calls.append(kwargs)
        return {'success': True}

    monkeypatch.setattr(WhatsAppService, 'send_message', _fake_send_message)

    result = SchedulerService.send_end_session_prompts()
    return result, sent_calls


def test_end_session_prompt_coach_lookup_passes_session_org_id(monkeypatch):
    session = _ended_session_needing_prompt(org_id='org-a', coach_id='coach-9')
    result, sent_calls = _run_end_session_prompts_job(
        monkeypatch, session,
        coaches_by_id={'coach-9': {'org_id': 'org-a', 'name': 'Coach Nine', 'phone_number': '0821234567'}},
    )

    assert result['success'] is True
    assert result['prompts_sent'] == 1
    assert len(sent_calls) == 1
    assert 'Coach Nine' in sent_calls[0]['message_text']


def test_end_session_prompt_coach_lookup_does_not_return_a_coach_from_another_org(monkeypatch):
    session = _ended_session_needing_prompt(org_id='org-a', coach_id='coach-9')
    result, sent_calls = _run_end_session_prompts_job(
        monkeypatch, session,
        coaches_by_id={'coach-9': {'org_id': 'org-b', 'name': 'Coach Nine (other org)', 'phone_number': '0821234567'}},
    )

    assert result['success'] is True
    assert result['prompts_sent'] == 0
    assert len(sent_calls) == 0
