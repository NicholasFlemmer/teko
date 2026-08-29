"""Unit tests for on-demand session creation over WhatsApp (Cricket without
Boundaries feature 1 of 5): a coach sends /session, picks which of their
teams it's for, and a real session document is created for today so the
existing (untouched) location check-in flow finds it.

Pure unit tests: PersonService, FirebaseService, GeminiService, and
WhatsAppService are all stubbed via monkeypatch -- same convention as
test_command_permissions.py and test_gps_checkin_org_scoping.py. Pending
start-session state (get_pending_session/set_pending_session/
clear_pending_session) is exercised for real against an in-memory fake
Firestore db (same pattern as _RaisingDb in test_step3c_fixes.py and the
fake db in test_gps_checkin_org_scoping.py), so this also proves the actual
document-ID/TTL wiring, not just a mocked stand-in for it.

Usage:
    cd backend
    pytest tests/test_start_session.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) now lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

from datetime import date, datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from services.person_service import PersonService  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
from services.gemini_service import GeminiService  # noqa: E402
from services.whatsapp_service import WhatsAppService  # noqa: E402


# ---------------------------------------------------------------------------
# In-memory fake Firestore db -- backs get_pending_session/set_pending_
# session/clear_pending_session for real, so the TTL/doc-shape tests exercise
# the actual implementation rather than a mock standing in for it.
# ---------------------------------------------------------------------------

class _FakeDocSnapshot:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data)


class _FakeDocRef:
    def __init__(self, store, key):
        self._store = store
        self._key = key

    def get(self):
        return _FakeDocSnapshot(self._store.get(self._key))

    def set(self, data):
        self._store[self._key] = data

    def delete(self):
        self._store.pop(self._key, None)


class _FakeCollection:
    def __init__(self, store):
        self._store = store

    def document(self, key):
        return _FakeDocRef(self._store, key)


class _FakeDb:
    def __init__(self):
        self._collections = {}

    def collection(self, name):
        return _FakeCollection(self._collections.setdefault(name, {}))


@pytest.fixture
def fake_db(monkeypatch):
    db = _FakeDb()
    monkeypatch.setattr(FirebaseService, 'get_db', lambda: db)
    return db


def _coach(org_id='org-a', coach_id='coach-1', phone='27821234567', name='Alex'):
    return {
        'id': coach_id,
        'org_id': org_id,
        'name': name,
        'phone_number': phone,
        'person_type': 'coach',
    }


def _team(team_id, name, coach_ids, location_id=None, org_id='org-a'):
    t = {'id': team_id, 'name': name, 'coach_ids': coach_ids, 'org_id': org_id}
    if location_id is not None:
        t['location_id'] = location_id
    return t


@pytest.fixture
def drive(monkeypatch, fake_db):
    """Drive a WhatsApp text message through the real handle_incoming_message
    entry point, with every underlying data call stubbed except the
    pending-state helpers (which run for real against fake_db)."""
    monkeypatch.setattr(GeminiService, 'generate_custom_message', lambda prompt: "STUBBED AI REPLY")
    monkeypatch.setattr(ConversationService, 'get_conversation_history', classmethod(lambda cls, phone, limit=10: []))
    monkeypatch.setattr(ConversationService, 'save_message', classmethod(lambda cls, phone, role, content: None))
    monkeypatch.setattr(FirebaseService, 'get_all_content', lambda org_id: [])
    monkeypatch.setattr(FirebaseService, 'get_all_urls', lambda org_id: [])
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda oid: {'id': oid, 'type': 'sports'})

    def _drive(coach, text):
        monkeypatch.setattr(PersonService, 'resolve', lambda phone: dict(coach))

        sent = {}

        def _fake_send(phone_number, message_text):
            sent['message_text'] = message_text
            return {'success': True}

        monkeypatch.setattr(WhatsAppService, 'send_message', _fake_send)

        ConversationService.handle_incoming_message(coach['phone_number'], text, message_id='start-session-test')
        return sent.get('message_text')

    return _drive


AI_CALL_MARKER = "STUBBED AI REPLY"


# ---------------------------------------------------------------------------
# 1. One team -> session created immediately, no question asked.
# ---------------------------------------------------------------------------

def test_one_team_creates_session_immediately_no_question_asked(drive, monkeypatch):
    coach = _coach()
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [])
    monkeypatch.setattr(FirebaseService, 'get_all_teams', lambda org_id, location_id=None: [
        _team('team-1', 'U12s', ['coach-1']),
    ])

    created = {}
    monkeypatch.setattr(FirebaseService, 'create_session', lambda data: created.update(data) or {'id': 'sess-new', **data})

    reply = drive(coach, '/session')

    assert created.get('team_id') == 'team-1'
    assert 'U12s' in reply
    assert 'started' in reply.lower()
    assert 'location' in reply.lower()
    # No team-choice question was ever asked.
    assert 'which' not in reply.lower()
    assert '1.' not in reply


# ---------------------------------------------------------------------------
# 2. Three teams -> numbered list sent, nothing created yet.
# ---------------------------------------------------------------------------

def test_three_teams_sends_numbered_list_creates_nothing_yet(drive, monkeypatch):
    coach = _coach()
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [])
    monkeypatch.setattr(FirebaseService, 'get_all_teams', lambda org_id, location_id=None: [
        _team('team-1', 'U12s', ['coach-1']),
        _team('team-2', 'U14s', ['coach-1']),
        _team('team-3', 'U16s', ['coach-1']),
    ])

    create_calls = []
    monkeypatch.setattr(FirebaseService, 'create_session', lambda data: create_calls.append(data) or {'id': 'x'})

    reply = drive(coach, '/session')

    assert 'U12s' in reply and 'U14s' in reply and 'U16s' in reply
    assert '1.' in reply and '2.' in reply and '3.' in reply
    assert create_calls == []


# ---------------------------------------------------------------------------
# 3. Replying with a valid number creates the session for the right team.
# ---------------------------------------------------------------------------

def test_valid_number_reply_creates_session_for_right_team(drive, monkeypatch):
    coach = _coach()
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [])
    monkeypatch.setattr(FirebaseService, 'get_all_teams', lambda org_id, location_id=None: [
        _team('team-1', 'U12s', ['coach-1']),
        _team('team-2', 'U14s', ['coach-1']),
    ])
    monkeypatch.setattr(FirebaseService, 'get_team', lambda team_id, org_id: (
        _team('team-2', 'U14s', ['coach-1']) if team_id == 'team-2' else None
    ))

    created = {}
    monkeypatch.setattr(FirebaseService, 'create_session', lambda data: created.update(data) or {'id': 'sess-new', **data})

    first_reply = drive(coach, '/session')
    assert 'U12s' in first_reply and 'U14s' in first_reply  # pending question asked

    second_reply = drive(coach, '2')  # picks the second listed team, U14s

    assert created.get('team_id') == 'team-2'
    assert 'U14s' in second_reply
    assert 'started' in second_reply.lower()


# ---------------------------------------------------------------------------
# 4. Invalid number -> re-prompt, creates nothing.
# ---------------------------------------------------------------------------

def test_invalid_number_reply_reprompts_and_creates_nothing(drive, monkeypatch):
    coach = _coach()
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [])
    monkeypatch.setattr(FirebaseService, 'get_all_teams', lambda org_id, location_id=None: [
        _team('team-1', 'U12s', ['coach-1']),
        _team('team-2', 'U14s', ['coach-1']),
    ])
    create_calls = []
    monkeypatch.setattr(FirebaseService, 'create_session', lambda data: create_calls.append(data) or {'id': 'x'})

    drive(coach, '/session')
    reply = drive(coach, '9')  # out of range -- only 2 teams listed

    assert create_calls == []
    assert '1.' in reply and '2.' in reply  # re-prompted with the same list


# ---------------------------------------------------------------------------
# 5. Free text -> re-prompt, never reaches the AI handler.
# ---------------------------------------------------------------------------

def test_free_text_reply_reprompts_and_does_not_reach_ai(drive, monkeypatch):
    coach = _coach()
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [])
    monkeypatch.setattr(FirebaseService, 'get_all_teams', lambda org_id, location_id=None: [
        _team('team-1', 'U12s', ['coach-1']),
        _team('team-2', 'U14s', ['coach-1']),
    ])
    create_calls = []
    monkeypatch.setattr(FirebaseService, 'create_session', lambda data: create_calls.append(data) or {'id': 'x'})

    drive(coach, '/session')
    reply = drive(coach, 'what drills should I run today?')

    assert create_calls == []
    assert AI_CALL_MARKER not in reply
    assert '1.' in reply and '2.' in reply


# ---------------------------------------------------------------------------
# 6. pending_session expires after 1800s and is deleted on read.
# ---------------------------------------------------------------------------

def test_pending_session_expires_after_1800s_and_is_deleted_on_read(fake_db):
    phone = '27821234567'
    key = ConversationService._phone_key(phone)
    stale_created_at = datetime.now(timezone.utc) - timedelta(seconds=1801)
    fake_db.collection('pending_session').document(key).set({
        'teams': [{'id': 'team-1', 'name': 'U12s'}],
        'org_id': 'org-a',
        'coach_id': 'coach-1',
        'created_at': stale_created_at,
    })

    result = ConversationService.get_pending_session(phone)

    assert result is None
    # Deleted, not just ignored -- the doc must actually be gone.
    assert fake_db.collection('pending_session').document(key).get().exists is False


def test_pending_session_not_yet_expired_is_returned(fake_db):
    phone = '27821234567'
    key = ConversationService._phone_key(phone)
    fresh_created_at = datetime.now(timezone.utc) - timedelta(seconds=60)
    fake_db.collection('pending_session').document(key).set({
        'teams': [{'id': 'team-1', 'name': 'U12s'}],
        'org_id': 'org-a',
        'coach_id': 'coach-1',
        'created_at': fresh_created_at,
    })

    result = ConversationService.get_pending_session(phone)

    assert result is not None
    assert result['teams'] == [{'id': 'team-1', 'name': 'U12s'}]


# ---------------------------------------------------------------------------
# 7. Zero teams -> right message, no session created.
# ---------------------------------------------------------------------------

def test_zero_teams_gets_not_linked_message_and_creates_no_session(drive, monkeypatch):
    coach = _coach()
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [])
    monkeypatch.setattr(FirebaseService, 'get_all_teams', lambda org_id, location_id=None: [])
    create_calls = []
    monkeypatch.setattr(FirebaseService, 'create_session', lambda data: create_calls.append(data) or {'id': 'x'})

    reply = drive(coach, '/session')

    assert create_calls == []
    assert 'not linked' in reply.lower()
    assert 'administrator' in reply.lower()


# ---------------------------------------------------------------------------
# 8. A session already exists today -> right message, no second session.
# ---------------------------------------------------------------------------

def test_existing_session_today_refuses_a_second_one(drive, monkeypatch):
    coach = _coach()
    today_str = date.today().strftime('%Y-%m-%d')
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [
        {'id': 'sess-existing', 'date': today_str, 'coach_id': 'coach-1'},
    ])
    get_all_teams_called = {'value': False}
    monkeypatch.setattr(FirebaseService, 'get_all_teams', lambda org_id, location_id=None: get_all_teams_called.__setitem__('value', True) or [])
    create_calls = []
    monkeypatch.setattr(FirebaseService, 'create_session', lambda data: create_calls.append(data) or {'id': 'x'})

    reply = drive(coach, '/session')

    assert create_calls == []
    assert 'already have a' in reply.lower() or 'already' in reply.lower()
    assert 'location' in reply.lower()
    # Refusal happens before team lookup -- not required by the task, but
    # confirms the check-for-existing-session step runs first.
    assert get_all_teams_called['value'] is False


# ---------------------------------------------------------------------------
# 9. org_id on the created doc, and cross-org isolation of the lookups.
# ---------------------------------------------------------------------------

def test_org_scoping_reads_and_write_all_use_the_coachs_own_org(drive, monkeypatch):
    coach = _coach(org_id='org-a', coach_id='coach-1')
    calls = {}

    def _fake_get_all_sessions(org_id, coach_id=None, **kw):
        calls['sessions_org_id'] = org_id
        return []

    def _fake_get_all_teams(org_id, location_id=None):
        calls['teams_org_id'] = org_id
        return [_team('team-1', 'U12s', ['coach-1'], org_id=org_id)]

    created = {}
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', _fake_get_all_sessions)
    monkeypatch.setattr(FirebaseService, 'get_all_teams', _fake_get_all_teams)
    monkeypatch.setattr(FirebaseService, 'create_session', lambda data: created.update(data) or {'id': 'sess-new', **data})

    drive(coach, '/session')

    assert calls['sessions_org_id'] == 'org-a'
    assert calls['teams_org_id'] == 'org-a'
    assert created['org_id'] == 'org-a'
    # A coach resolved under org-a can never end up writing/reading org-b.
    assert 'org-b' not in calls.values()
    assert created['org_id'] != 'org-b'


# ---------------------------------------------------------------------------
# 10. team_id/team_ids agree, coach_id/coach_ids agree.
# ---------------------------------------------------------------------------

def test_created_document_has_consistent_id_and_ids_fields(drive, monkeypatch):
    coach = _coach(org_id='org-a', coach_id='coach-1')
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [])
    monkeypatch.setattr(FirebaseService, 'get_all_teams', lambda org_id, location_id=None: [
        _team('team-1', 'U12s', ['coach-1']),
    ])
    created = {}
    monkeypatch.setattr(FirebaseService, 'create_session', lambda data: created.update(data) or {'id': 'sess-new', **data})

    drive(coach, '/session')

    assert created['team_id'] == 'team-1'
    assert created['team_ids'] == ['team-1']
    assert created['coach_id'] == 'coach-1'
    assert created['coach_ids'] == ['coach-1']
    assert created['type'] == 'practice'
    assert created['date'] == date.today().strftime('%Y-%m-%d')


# ---------------------------------------------------------------------------
# 11. location_id omitted (not empty string) when the team has none.
# ---------------------------------------------------------------------------

def test_location_id_omitted_not_empty_string_when_team_has_none(drive, monkeypatch):
    coach = _coach()
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [])
    monkeypatch.setattr(FirebaseService, 'get_all_teams', lambda org_id, location_id=None: [
        _team('team-1', 'U12s', ['coach-1']),  # no location_id at all
    ])
    created = {}
    monkeypatch.setattr(FirebaseService, 'create_session', lambda data: created.update(data) or {'id': 'sess-new', **data})

    drive(coach, '/session')

    assert created.get('team_id') == 'team-1'  # the session was actually created
    assert 'location_id' not in created


def test_location_id_present_when_team_has_one(drive, monkeypatch):
    coach = _coach()
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [])
    monkeypatch.setattr(FirebaseService, 'get_all_teams', lambda org_id, location_id=None: [
        _team('team-1', 'U12s', ['coach-1'], location_id='loc-1'),
    ])
    created = {}
    monkeypatch.setattr(FirebaseService, 'create_session', lambda data: created.update(data) or {'id': 'sess-new', **data})

    drive(coach, '/session')

    assert created.get('location_id') == 'loc-1'


# ---------------------------------------------------------------------------
# 12. Creation failure logs ERROR, replies to the coach, leaves no
#     pending_session document behind.
# ---------------------------------------------------------------------------

def test_creation_failure_logs_error_replies_and_clears_pending(drive, monkeypatch, caplog, fake_db):
    coach = _coach(org_id='org-a', coach_id='coach-1')
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [])
    monkeypatch.setattr(FirebaseService, 'get_all_teams', lambda org_id, location_id=None: [
        _team('team-1', 'U12s', ['coach-1']),
        _team('team-2', 'U14s', ['coach-1']),
    ])
    monkeypatch.setattr(FirebaseService, 'get_team', lambda team_id, org_id: _team(team_id, 'U14s', ['coach-1']))

    def _raise(data):
        raise RuntimeError("Firestore write failed")

    monkeypatch.setattr(FirebaseService, 'create_session', _raise)

    drive(coach, '/session')  # sets pending_session (2 teams)
    key = ConversationService._phone_key(coach['phone_number'])
    assert fake_db.collection('pending_session').document(key).get().exists is True

    with caplog.at_level('ERROR'):
        reply = drive(coach, '2')

    assert 'could not be started' in reply.lower()
    assert any(
        r.levelname == 'ERROR'
        and 'org_id=org-a' in r.message
        and 'coach_id=coach-1' in r.message
        and 'team_id=team-2' in r.message
        for r in caplog.records
    )
    # No pending_session document survives a failed attempt.
    assert fake_db.collection('pending_session').document(key).get().exists is False


# ---------------------------------------------------------------------------
# 13. handle_location_check_in is unchanged -- its existing refusal
#     behaviour still passes.
# ---------------------------------------------------------------------------

def test_location_check_in_refusal_unchanged(monkeypatch):
    coach = _coach(org_id='org-a', coach_id='coach-1', phone='0821234567')
    monkeypatch.setattr(PersonService, 'resolve', lambda phone: dict(coach))
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [])

    sent = {}
    monkeypatch.setattr(WhatsAppService, 'send_message',
                         lambda phone_number, message_text: sent.update(message_text=message_text) or {'success': True})

    ConversationService.handle_location_check_in('+27821234567', -33.9, 18.4)

    assert sent.get('message_text') == "You don't have a session scheduled for today. 📋"
