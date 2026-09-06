"""Unit tests for the missed-check-in nudge feature in
services/scheduler_service.py's mark_missed_sessions().

Cricket without Boundaries: coaches whose session gets marked 'missed' now
get an automated WhatsApp nudge, gated per org by the new
missed_checkin_nudges field (defaults to False -- see
mark_missed_sessions' own docstring for the attendance_mode-pattern
reuse this copies).

Covers:
  - a missed session in an org with the flag ON sends exactly one nudge
  - the SAME session on a second run of mark_missed_sessions() sends
    nothing more (the session is no longer status='reminded', so the
    job's own query can't re-select it -- see _FakeSessionsStore below,
    which actually mutates on update() so two sequential calls behave
    like two real scheduler runs against the same Firestore data)
  - a missed session in an org with the flag OFF sends nothing
  - an org with no missed_checkin_nudges field at all (CATCH Trust's
    current state) writes the exact same {'status': 'missed'} Firestore
    update as before this feature existed, and sends nothing -- pins
    the same behaviour tests/test_missed_status_fix.py already covers

Pure unit tests: FirebaseService.get_db/update_session/get_organisation/
get_org_terminology/get_coach, WhatsAppService.send_message, and
ConversationService.save_message are all monkeypatched with in-memory
fakes (same convention as tests/test_missed_status_fix.py), so nothing
here touches real Firestore or the real WhatsApp API.

Usage:
    cd backend
    pytest tests/test_missed_checkin_nudges.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) now lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

from datetime import datetime, timedelta, timezone  # noqa: E402

from services.conversation_service import ConversationService  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
from services.scheduler_service import SchedulerService  # noqa: E402
from services.whatsapp_service import WhatsAppService  # noqa: E402


# ---------------------------------------------------------------------------
# Stateful fakes -- unlike test_missed_status_fix.py's capture-only fake,
# this one actually mutates the stored doc on update_session(), so calling
# mark_missed_sessions() twice against the SAME store behaves like two real
# scheduler runs against the same Firestore data: the second run's own
# where('status', '==', 'reminded') query genuinely no longer returns a
# session this store already flipped to 'missed'.
# ---------------------------------------------------------------------------

class _FakeDoc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return self._data


class _FakeSessionsStore:
    def __init__(self, sessions):
        self._docs = {s['id']: {k: v for k, v in s.items() if k != 'id'} for s in sessions}
        self.update_calls = []

    def reminded_docs(self):
        return [
            _FakeDoc(doc_id, dict(data))
            for doc_id, data in self._docs.items()
            if data.get('status') == 'reminded'
        ]

    def update(self, session_id, data):
        self.update_calls.append((session_id, dict(data)))
        self._docs[session_id].update(data)


class _FakeQueryable:
    def __init__(self, store):
        self._store = store

    def where(self, *args, **kwargs):
        return self

    def stream(self):
        return iter(self._store.reminded_docs())


class _FakeDb:
    def __init__(self, store):
        self._store = store

    def collection(self, name):
        assert name == 'sessions'
        return _FakeQueryable(self._store)


def _past_session(session_id='sess-past', org_id='org-1', coach_id='coach-1', **extra):
    """A session whose end_time is safely in the past, org_id set (so the
    nudge path's org lookup actually runs -- see mark_missed_sessions'
    `if session_org_id` guard)."""
    end = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
    start = end - timedelta(hours=1)
    session = {
        'id': session_id,
        'status': 'reminded',
        'org_id': org_id,
        'coach_id': coach_id,
        'date': end.strftime('%Y-%m-%d'),
        'start_time': start.strftime('%H:%M'),
        'end_time': end.strftime('%H:%M'),
    }
    session.update(extra)
    return session


def _install_fakes(monkeypatch, sessions, orgs, coaches, send_result=None):
    """orgs: dict of org_id -> org dict (or {} / missing entirely to
    simulate an org with no missed_checkin_nudges field, e.g. CATCH).
    coaches: dict of coach_id -> coach dict.

    Returns (store, whatsapp_calls).
    """
    store = _FakeSessionsStore(sessions)
    monkeypatch.setattr(FirebaseService, 'get_db', lambda: _FakeDb(store))
    monkeypatch.setattr(FirebaseService, 'update_session', store.update)
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: orgs.get(org_id))
    monkeypatch.setattr(FirebaseService, 'get_org_terminology', lambda org_id: {'session_singular': 'Session'})
    monkeypatch.setattr(FirebaseService, 'get_coach', lambda coach_id, org_id: coaches.get(coach_id))
    monkeypatch.setattr(ConversationService, 'save_message', lambda *a, **k: None)

    whatsapp_calls = []

    def _fake_send_message(phone_number, message_text, check_in_url=None):
        whatsapp_calls.append({'phone_number': phone_number, 'message_text': message_text})
        return send_result if send_result is not None else {'success': True}

    monkeypatch.setattr(WhatsAppService, 'send_message', _fake_send_message)
    return store, whatsapp_calls


_COACH = {'coach-1': {'name': 'Jo', 'phone_number': '27000000101'}}


# ---------------------------------------------------------------------------
# Flag ON: exactly one nudge
# ---------------------------------------------------------------------------

def test_missed_session_flag_on_sends_one_nudge(monkeypatch):
    session = _past_session()
    orgs = {'org-1': {'id': 'org-1', 'type': 'sports', 'missed_checkin_nudges': True}}
    store, whatsapp_calls = _install_fakes(monkeypatch, [session], orgs, _COACH)

    result = SchedulerService.mark_missed_sessions()

    assert result['success'] is True
    assert result['sessions_marked_missed'] == 1
    assert result['nudges_sent'] == 1

    assert len(whatsapp_calls) == 1
    assert whatsapp_calls[0]['phone_number'] == '27000000101'
    message = whatsapp_calls[0]['message_text']
    assert 'Jo' in message
    assert session['date'] in message
    assert session['start_time'] in message

    assert len(store.update_calls) == 1
    session_id, update_data = store.update_calls[0]
    assert session_id == session['id']
    assert update_data == {'status': 'missed', 'missed_checkin_nudge_sent': True}


# ---------------------------------------------------------------------------
# Rerun: the same session sends nothing on a second run
# ---------------------------------------------------------------------------

def test_rerun_of_same_session_sends_nothing_more(monkeypatch):
    session = _past_session()
    orgs = {'org-1': {'id': 'org-1', 'type': 'sports', 'missed_checkin_nudges': True}}
    store, whatsapp_calls = _install_fakes(monkeypatch, [session], orgs, _COACH)

    first = SchedulerService.mark_missed_sessions()
    assert first['nudges_sent'] == 1
    assert len(whatsapp_calls) == 1

    second = SchedulerService.mark_missed_sessions()

    assert second['success'] is True
    assert second['sessions_marked_missed'] == 0
    assert second['nudges_sent'] == 0
    # No new WhatsApp send and no new Firestore write -- the session is no
    # longer status='reminded', so the job's own query never re-selects it.
    assert len(whatsapp_calls) == 1
    assert len(store.update_calls) == 1


# ---------------------------------------------------------------------------
# Flag OFF: no message
# ---------------------------------------------------------------------------

def test_missed_session_flag_off_sends_nothing(monkeypatch):
    session = _past_session()
    orgs = {'org-1': {'id': 'org-1', 'type': 'sports', 'missed_checkin_nudges': False}}
    store, whatsapp_calls = _install_fakes(monkeypatch, [session], orgs, _COACH)

    result = SchedulerService.mark_missed_sessions()

    assert result['success'] is True
    assert result['sessions_marked_missed'] == 1
    assert result['nudges_sent'] == 0
    assert whatsapp_calls == []

    assert len(store.update_calls) == 1
    session_id, update_data = store.update_calls[0]
    assert session_id == session['id']
    # No missed_checkin_nudge_sent field at all when the flag is off.
    assert update_data == {'status': 'missed'}


# ---------------------------------------------------------------------------
# CATCH's current behaviour: no missed_checkin_nudges field at all
# ---------------------------------------------------------------------------

def test_org_with_no_nudges_field_behaves_exactly_as_before(monkeypatch):
    """Pins tests/test_missed_status_fix.py's own
    test_mark_missed_no_check_in_evidence_is_marked_missed assertion
    (captured == [(session['id'], {'status': 'missed'})]) for an org that
    exists but has never set missed_checkin_nudges -- e.g. CATCH Trust
    today. Absent reads as False, same as attendance_mode's own pattern."""
    session = _past_session()
    orgs = {'org-1': {'id': 'org-1', 'type': 'ngo'}}  # no missed_checkin_nudges key
    store, whatsapp_calls = _install_fakes(monkeypatch, [session], orgs, _COACH)

    result = SchedulerService.mark_missed_sessions()

    assert result['success'] is True
    assert result['sessions_marked_missed'] == 1
    assert result['nudges_sent'] == 0
    assert whatsapp_calls == []
    assert store.update_calls == [(session['id'], {'status': 'missed'})]


def test_session_with_no_org_id_behaves_exactly_as_before(monkeypatch):
    """Same pin as above, for a session with no org_id at all -- exactly
    the fixture shape tests/test_missed_status_fix.py uses. The
    `if session_org_id` guard means get_organisation is never even
    called, matching that file's fakes (which only implement the
    'sessions' collection)."""
    session = _past_session(org_id=None)
    del session['org_id']
    store, whatsapp_calls = _install_fakes(monkeypatch, [session], orgs={}, coaches=_COACH)

    result = SchedulerService.mark_missed_sessions()

    assert result['success'] is True
    assert result['nudges_sent'] == 0
    assert whatsapp_calls == []
    assert store.update_calls == [(session['id'], {'status': 'missed'})]


def test_rescued_session_never_gets_a_nudge(monkeypatch):
    """A session with check-in evidence is rescued to 'checked_in', not
    marked missed -- it must never be nudged, even with the flag on."""
    session = _past_session(coach_check_ins={'coach-1': {'check_in_time': 'x'}})
    orgs = {'org-1': {'id': 'org-1', 'type': 'sports', 'missed_checkin_nudges': True}}
    store, whatsapp_calls = _install_fakes(monkeypatch, [session], orgs, _COACH)

    result = SchedulerService.mark_missed_sessions()

    assert result['nudges_sent'] == 0
    assert whatsapp_calls == []
    assert store.update_calls == [(session['id'], {'status': 'checked_in'})]
