"""Unit tests for headcount-mode /attendance (Cricket without Boundaries
feature 2 of 5): an org with attendance_mode='headcount' records boys/
girls/new-participant counts instead of a named player register, and
never requires a single player document to exist.

Covers:
  - attendance_mode='named' (or absent, the default) is completely
    unchanged -- still calls get_all_players, still builds the numbered
    player-list prompt. This is the regression guarantee for every
    existing org (see also tests/test_step3c_fixes.py, unmodified).
  - attendance_mode='headcount' never calls get_all_players, prompts for
    boys/girls/new as three numbers, and can record with zero player
    documents in existence.
  - Reply parsing: space- and comma-separated triples, wrong-count/non-
    numeric re-prompts, new > boys+girls rejected, all-zeros rejected,
    'cancel'.
  - pending_headcount storage: doc shape, 1800s TTL (same convention as
    pending_attendance/pending_session), deleted on expired read.
  - The written session document: 'headcount' populated, attended_player_
    ids never touched.
  - After recording, pending_photo is set and the existing (untouched)
    handle_image_message flow still writes group_photo to the session.
  - /attendance-redo clears 'headcount' (not attended_player_ids) in
    headcount mode, then re-prompts.
  - A second /attendance with a headcount already recorded reports the
    numbers back and does not set new pending state.
  - Two orgs in different attendance_mode resolve independently in the
    same process (mirrors tests/test_org_timezone.py's independent-orgs
    test for get_org_now).

Pure unit tests: FirebaseService is stubbed via monkeypatch (or backed by
an in-memory fake Firestore db for the pending_headcount storage tests,
same pattern as tests/test_start_session.py's _FakeDb), so nothing here
touches real infrastructure.

Usage:
    cd backend
    pytest tests/test_headcount_attendance.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) now lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from services.person_service import PersonService  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
from services.whatsapp_service import WhatsAppService  # noqa: E402
from services.storage_service import StorageService  # noqa: E402


# ---------------------------------------------------------------------------
# In-memory fake Firestore db -- same pattern as test_start_session.py's
# _FakeDb, backing get_pending_headcount/set_pending_headcount/
# clear_pending_headcount for real so the TTL/doc-shape tests exercise the
# actual implementation.
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


def _org(attendance_mode=None):
    d = {'id': 'org-a', 'type': 'sports'}
    if attendance_mode is not None:
        d['attendance_mode'] = attendance_mode
    return d


def _session(session_id='session-1', org_id='org-a', team_id='team-1', date_str='2026-08-30', **extra):
    base = {
        'id': session_id,
        'org_id': org_id,
        'team_id': team_id,
        'date': date_str,
        'start_time': '10:00',
        'type': 'practice',
        'coach_id': 'coach-1',
        'coach_ids': ['coach-1'],
    }
    base.update(extra)
    return base


def _pending(session_id='session-1', team_id='team-1', org_id='org-a'):
    return {
        'session_id': session_id,
        'team_id': team_id,
        'org_id': org_id,
        'created_at': datetime.now(timezone.utc),
    }


# ---------------------------------------------------------------------------
# 1. 'named' mode (and absent attendance_mode, the default) is unchanged.
# ---------------------------------------------------------------------------

def test_named_mode_still_calls_get_all_players_and_prompts_player_list(monkeypatch):
    monkeypatch.setattr(FirebaseService, 'get_org_now', lambda org_id: datetime(2026, 8, 30, 10, 0))
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org(attendance_mode='named'))
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [_session()])
    monkeypatch.setattr(FirebaseService, 'get_team', lambda team_id, org_id: {'id': team_id, 'name': 'U12s'})
    calls = []

    def _get_all_players(org_id, team_id=None):
        calls.append((org_id, team_id))
        return [{'id': 'p1', 'first_name': 'Amy', 'last_name': 'A'}]

    monkeypatch.setattr(FirebaseService, 'get_all_players', _get_all_players)
    monkeypatch.setattr(ConversationService, 'set_pending_attendance', classmethod(lambda cls, phone, sid, players: None))

    reply = ConversationService.handle_attendance_command(_coach())

    assert calls == [('org-a', 'team-1')], "named mode must still call get_all_players"
    assert 'ABSENT' in reply
    assert '1. Amy A' in reply


def test_absent_attendance_mode_defaults_to_named(monkeypatch):
    """No attendance_mode field at all (every existing org today) must
    behave exactly like 'named' -- default, not an error, not headcount."""
    monkeypatch.setattr(FirebaseService, 'get_org_now', lambda org_id: datetime(2026, 8, 30, 10, 0))
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: {'id': 'org-a', 'type': 'sports'})
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [_session()])
    monkeypatch.setattr(FirebaseService, 'get_team', lambda team_id, org_id: {'id': team_id, 'name': 'U12s'})
    monkeypatch.setattr(FirebaseService, 'get_all_players',
                         lambda org_id, team_id=None: [{'id': 'p1', 'first_name': 'Amy', 'last_name': 'A'}])
    monkeypatch.setattr(ConversationService, 'set_pending_attendance', classmethod(lambda cls, phone, sid, players: None))

    reply = ConversationService.handle_attendance_command(_coach())

    assert 'ABSENT' in reply


# ---------------------------------------------------------------------------
# 2 & 3. 'headcount' mode: never calls get_all_players, prompts even with
# zero player documents.
# ---------------------------------------------------------------------------

def test_headcount_mode_never_calls_get_all_players_and_prompts_headcount(monkeypatch):
    monkeypatch.setattr(FirebaseService, 'get_org_now', lambda org_id: datetime(2026, 8, 30, 10, 0))
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org(attendance_mode='headcount'))
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [_session()])
    monkeypatch.setattr(FirebaseService, 'get_team', lambda team_id, org_id: {'id': team_id, 'name': 'Sub-15'})

    def _boom(*a, **kw):
        raise AssertionError("headcount mode must never call get_all_players")

    monkeypatch.setattr(FirebaseService, 'get_all_players', _boom)
    monkeypatch.setattr(ConversationService, 'set_pending_headcount', classmethod(lambda cls, phone, sid, tid, oid: None))

    reply = ConversationService.handle_attendance_command(_coach())

    assert 'boys' in reply.lower()
    assert 'girls' in reply.lower()
    assert 'new' in reply.lower()
    assert 'cancel' in reply.lower()
    assert '12 8 3' in reply


def test_headcount_org_with_zero_player_documents_can_still_record(monkeypatch, fake_db):
    """The whole point of this mode: a team with zero player documents in
    Firestore must still get the prompt and be able to record."""
    session_store = {'session-1': _session()}
    monkeypatch.setattr(FirebaseService, 'get_org_now', lambda org_id: datetime(2026, 8, 30, 10, 0))
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org(attendance_mode='headcount'))
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [dict(session_store['session-1'])])
    monkeypatch.setattr(FirebaseService, 'get_team', lambda team_id, org_id: {'id': team_id, 'name': 'Sub-15'})
    monkeypatch.setattr(FirebaseService, 'get_all_players', lambda org_id, team_id=None: [])

    def _update_session(sid, data):
        session_store[sid].update(data)
        return dict(session_store[sid])

    monkeypatch.setattr(FirebaseService, 'update_session', _update_session)
    import services.conversation_service as cs_module
    monkeypatch.setattr(cs_module, 'push_event', lambda *a, **kw: None)

    prompt = ConversationService.handle_attendance_command(_coach())
    assert 'boys' in prompt.lower()

    pending = ConversationService.get_pending_headcount('27821234567')
    assert pending is not None
    reply = ConversationService.handle_headcount_response(_coach(), '27821234567', '12 8 3', pending)

    assert '✅' in reply
    assert session_store['session-1']['headcount']['total'] == 20


# ---------------------------------------------------------------------------
# 4 & 5. Space- and comma-separated triples parse identically.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('text', ['12 8 3', '12,8,3', '12, 8, 3'])
def test_valid_triple_records_boys_girls_new_and_total(monkeypatch, text):
    captured = {}
    monkeypatch.setattr(FirebaseService, 'update_session', lambda sid, data: captured.update({sid: data}))
    monkeypatch.setattr(ConversationService, 'clear_pending_headcount', classmethod(lambda cls, phone: None))
    monkeypatch.setattr(ConversationService, 'set_pending_photo', classmethod(lambda cls, phone, sid, tid: None))
    import services.conversation_service as cs_module
    monkeypatch.setattr(cs_module, 'push_event', lambda *a, **kw: None)

    reply = ConversationService.handle_headcount_response(_coach(), '27821234567', text, _pending())

    hc = captured['session-1']['headcount']
    assert hc['boys'] == 12
    assert hc['girls'] == 8
    assert hc['new_participants'] == 3
    assert hc['total'] == 20
    assert hc['recorded_by'] == 'coach-1'
    assert 'recorded_at' in hc
    assert '✅' in reply
    assert '20' in reply


# ---------------------------------------------------------------------------
# 6. Wrong count or non-numeric tokens re-prompt rather than falling
# through to the AI, and never write anything.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('text', ['12 8', '12 8 3 5', 'twelve 8 3'], ids=['two-numbers', 'four-numbers', 'non-numeric'])
def test_invalid_reply_shape_reprompts_and_does_not_write(monkeypatch, text):
    write_calls = []
    monkeypatch.setattr(FirebaseService, 'update_session', lambda sid, data: write_calls.append((sid, data)))

    reply = ConversationService.handle_headcount_response(_coach(), '27821234567', text, _pending())

    assert not write_calls
    assert '12 8 3' in reply  # the worked example, in the re-prompt


# ---------------------------------------------------------------------------
# 7. new_participants > boys + girls is rejected and re-prompts.
# ---------------------------------------------------------------------------

def test_new_participants_exceeding_boys_plus_girls_rejected(monkeypatch):
    write_calls = []
    monkeypatch.setattr(FirebaseService, 'update_session', lambda sid, data: write_calls.append((sid, data)))

    reply = ConversationService.handle_headcount_response(_coach(), '27821234567', '5 3 9', _pending())

    assert not write_calls
    assert "can't be more than" in reply


# ---------------------------------------------------------------------------
# 8. All-zeros is rejected and re-prompts.
# ---------------------------------------------------------------------------

def test_all_zeros_rejected(monkeypatch):
    write_calls = []
    monkeypatch.setattr(FirebaseService, 'update_session', lambda sid, data: write_calls.append((sid, data)))

    reply = ConversationService.handle_headcount_response(_coach(), '27821234567', '0 0 0', _pending())

    assert not write_calls
    assert 'zero' in reply.lower()


# ---------------------------------------------------------------------------
# 9. 'cancel' clears pending state and confirms.
# ---------------------------------------------------------------------------

def test_cancel_clears_pending_headcount_and_confirms(monkeypatch):
    cleared = []
    monkeypatch.setattr(ConversationService, 'clear_pending_headcount', classmethod(lambda cls, phone: cleared.append(phone)))
    write_calls = []
    monkeypatch.setattr(FirebaseService, 'update_session', lambda sid, data: write_calls.append((sid, data)))

    reply = ConversationService.handle_headcount_response(_coach(), '27821234567', 'cancel', _pending())

    assert cleared == ['27821234567']
    assert not write_calls
    assert 'cancel' in reply.lower()


# ---------------------------------------------------------------------------
# 10. pending_headcount: doc shape, 1800s TTL, deleted on expired read.
# ---------------------------------------------------------------------------

def test_set_pending_headcount_writes_expected_fields(fake_db):
    ConversationService.set_pending_headcount('27821234567', 'session-1', 'team-1', 'org-a')

    key = ConversationService._phone_key('27821234567')
    doc = fake_db.collection('pending_headcount').document(key).get()
    assert doc.exists
    data = doc.to_dict()
    assert data['session_id'] == 'session-1'
    assert data['team_id'] == 'team-1'
    assert data['org_id'] == 'org-a'
    assert 'created_at' in data


def test_pending_headcount_expires_after_1800s_and_is_deleted_on_read(fake_db):
    phone = '27821234567'
    key = ConversationService._phone_key(phone)
    stale_created_at = datetime.now(timezone.utc) - timedelta(seconds=1801)
    fake_db.collection('pending_headcount').document(key).set({
        'session_id': 'session-1',
        'team_id': 'team-1',
        'org_id': 'org-a',
        'created_at': stale_created_at,
    })

    result = ConversationService.get_pending_headcount(phone)

    assert result is None
    # Deleted, not just ignored -- the doc must actually be gone.
    assert fake_db.collection('pending_headcount').document(key).get().exists is False


def test_pending_headcount_not_yet_expired_is_returned(fake_db):
    phone = '27821234567'
    key = ConversationService._phone_key(phone)
    fresh_created_at = datetime.now(timezone.utc) - timedelta(seconds=60)
    fake_db.collection('pending_headcount').document(key).set({
        'session_id': 'session-1',
        'team_id': 'team-1',
        'org_id': 'org-a',
        'created_at': fresh_created_at,
    })

    result = ConversationService.get_pending_headcount(phone)

    assert result is not None
    assert result['session_id'] == 'session-1'


# ---------------------------------------------------------------------------
# 11. The written session document: headcount populated, attended_player_
# ids never touched.
# ---------------------------------------------------------------------------

def test_written_session_has_headcount_and_attended_player_ids_untouched(monkeypatch):
    session_store = {'session-1': {'id': 'session-1', 'attended_player_ids': ['should-not-change']}}

    def _update_session(sid, data):
        session_store[sid].update(data)
        return dict(session_store[sid])

    monkeypatch.setattr(FirebaseService, 'update_session', _update_session)
    monkeypatch.setattr(ConversationService, 'clear_pending_headcount', classmethod(lambda cls, phone: None))
    monkeypatch.setattr(ConversationService, 'set_pending_photo', classmethod(lambda cls, phone, sid, tid: None))
    import services.conversation_service as cs_module
    monkeypatch.setattr(cs_module, 'push_event', lambda *a, **kw: None)

    ConversationService.handle_headcount_response(_coach(), '27821234567', '12 8 3', _pending())

    assert session_store['session-1']['headcount']['boys'] == 12
    assert session_store['session-1']['headcount']['girls'] == 8
    assert session_store['session-1']['headcount']['new_participants'] == 3
    assert session_store['session-1']['headcount']['total'] == 20
    assert session_store['session-1']['attended_player_ids'] == ['should-not-change']


# ---------------------------------------------------------------------------
# 12. Recording a headcount sets pending_photo, and the existing (untouched)
# photo flow still writes group_photo to the session.
# ---------------------------------------------------------------------------

def test_headcount_recording_sets_pending_photo_and_photo_flow_writes_group_photo(monkeypatch, fake_db):
    session_store = {'session-1': _session()}

    def _update_session(sid, data):
        session_store[sid].update(data)
        return dict(session_store[sid])

    def _get_session(sid, org_id):
        return dict(session_store[sid])

    monkeypatch.setattr(FirebaseService, 'update_session', _update_session)
    monkeypatch.setattr(FirebaseService, 'get_session', _get_session)
    monkeypatch.setattr(FirebaseService, 'update_team', lambda tid, data: None)
    import services.conversation_service as cs_module
    monkeypatch.setattr(cs_module, 'push_event', lambda *a, **kw: None)

    # 1. Record the headcount, using the real pending_headcount storage.
    ConversationService.set_pending_headcount('27821234567', 'session-1', 'team-1', 'org-a')
    pending = ConversationService.get_pending_headcount('27821234567')
    ConversationService.handle_headcount_response(_coach(), '27821234567', '12 8 3', pending)

    photo_pending = ConversationService.get_pending_photo('27821234567')
    assert photo_pending is not None
    assert photo_pending['session_id'] == 'session-1'
    assert photo_pending['team_id'] == 'team-1'

    # 2. The existing, untouched photo flow.
    monkeypatch.setattr(PersonService, 'resolve', lambda phone: _coach())
    monkeypatch.setattr(ConversationService, '_download_whatsapp_media',
                         classmethod(lambda cls, media_id: (b'fake-bytes', 'image/jpeg')))

    class _FakeBlob:
        def upload_from_string(self, data, content_type=None):
            pass

        def generate_signed_url(self, expiration=None, method=None):
            return 'https://example.com/photo.jpg'

    class _FakeBucket:
        def blob(self, path):
            return _FakeBlob()

    monkeypatch.setattr(StorageService, 'get_bucket', classmethod(lambda cls: _FakeBucket()))
    monkeypatch.setattr(WhatsAppService, 'send_message', lambda phone_number, message_text: {'success': True})

    ConversationService.handle_image_message('27821234567', {'id': 'media-1'}, message_id='m-1')

    assert session_store['session-1']['group_photo']['url'] == 'https://example.com/photo.jpg'
    # The headcount recorded in step 1 must still be there, untouched by
    # the photo write.
    assert session_store['session-1']['headcount']['boys'] == 12


# ---------------------------------------------------------------------------
# 13. /attendance-redo in headcount mode clears headcount, not
# attended_player_ids, then re-prompts.
# ---------------------------------------------------------------------------

def test_attendance_redo_headcount_mode_clears_headcount_and_reprompts(monkeypatch):
    session_store = {'session-1': _session(headcount={'boys': 5, 'girls': 5, 'new_participants': 1, 'total': 10})}
    monkeypatch.setattr(FirebaseService, 'get_org_now', lambda org_id: datetime(2026, 8, 30, 10, 0))
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org(attendance_mode='headcount'))
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [dict(session_store['session-1'])])
    monkeypatch.setattr(FirebaseService, 'get_team', lambda team_id, org_id: {'id': team_id, 'name': 'Sub-15'})
    monkeypatch.setattr(ConversationService, 'set_pending_headcount', classmethod(lambda cls, phone, sid, tid, oid: None))

    def _update_session(sid, data):
        session_store[sid].update(data)
        return dict(session_store[sid])

    monkeypatch.setattr(FirebaseService, 'update_session', _update_session)

    reply = ConversationService.handle_attendance_redo(_coach())

    assert session_store['session-1']['headcount'] is None
    assert session_store['session-1'].get('attended_player_ids') is None
    assert 'boys' in reply.lower()


# ---------------------------------------------------------------------------
# 14. A second /attendance with a headcount already recorded reports the
# numbers and does not set new pending state.
# ---------------------------------------------------------------------------

def test_second_attendance_command_reports_recorded_headcount(monkeypatch):
    session = _session(headcount={'boys': 12, 'girls': 8, 'new_participants': 3, 'total': 20})
    monkeypatch.setattr(FirebaseService, 'get_org_now', lambda org_id: datetime(2026, 8, 30, 10, 0))
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org(attendance_mode='headcount'))
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [session])

    def _boom(*a, **kw):
        raise AssertionError("must not call get_all_players")

    monkeypatch.setattr(FirebaseService, 'get_all_players', _boom)
    set_calls = []
    monkeypatch.setattr(ConversationService, 'set_pending_headcount', classmethod(lambda cls, *a: set_calls.append(a)))

    reply = ConversationService.handle_attendance_command(_coach())

    assert '20' in reply and '12' in reply and '8' in reply and '3' in reply
    assert 'attendance-redo' in reply.lower()
    assert not set_calls, "must not set new pending state when a headcount is already recorded"


# ---------------------------------------------------------------------------
# 15. Two orgs in different attendance_mode resolve independently in the
# same process.
# ---------------------------------------------------------------------------

def test_org_a_headcount_and_org_b_named_resolve_independently_same_process(monkeypatch):
    orgs = {'org-a': _org(attendance_mode='headcount'), 'org-b': {'id': 'org-b', 'type': 'sports'}}
    sessions = {
        'org-a': [_session(session_id='s-a', org_id='org-a', team_id='team-a')],
        'org-b': [_session(session_id='s-b', org_id='org-b', team_id='team-b')],
    }
    monkeypatch.setattr(FirebaseService, 'get_org_now', lambda org_id: datetime(2026, 8, 30, 10, 0))
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: orgs[org_id])
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: sessions[org_id])
    monkeypatch.setattr(FirebaseService, 'get_team', lambda team_id, org_id: {'id': team_id, 'name': 'Team'})

    def _get_all_players(org_id, team_id=None):
        if org_id == 'org-a':
            raise AssertionError("org-a is headcount mode, must not call get_all_players")
        return [{'id': 'p1', 'first_name': 'Amy', 'last_name': 'A'}]

    monkeypatch.setattr(FirebaseService, 'get_all_players', _get_all_players)
    monkeypatch.setattr(ConversationService, 'set_pending_headcount', classmethod(lambda cls, *a: None))
    monkeypatch.setattr(ConversationService, 'set_pending_attendance', classmethod(lambda cls, *a: None))

    reply_a = ConversationService.handle_attendance_command(_coach(org_id='org-a', coach_id='coach-a'))
    reply_b = ConversationService.handle_attendance_command(_coach(org_id='org-b', coach_id='coach-b'))

    assert 'boys' in reply_a.lower()
    assert 'ABSENT' in reply_b
