"""Regression tests for ConversationService.handle_location_check_in
(the WhatsApp-native GPS check-in flow) calling
FirebaseService.check_in_session() without an org_id -- it defaulted to
None even though the resolved coach's own org_id was already sitting in a
local variable two lines above.

Both branches of handle_location_check_in that call check_in_session are
covered:
  - the "no venue GPS configured" branch (session has no location_id)
  - the "distance verified" branch (session has a location with coordinates)

Usage:
    cd backend
    pytest tests/test_gps_checkin_org_scoping.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import date  # noqa: E402

from services.conversation_service import ConversationService  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
from services.person_service import PersonService  # noqa: E402
from services.whatsapp_service import WhatsAppService  # noqa: E402


def _coach(org_id='org-a', coach_id='coach-1', phone='0821234567'):
    return {
        'id': coach_id,
        'org_id': org_id,
        'name': 'Coach A',
        'phone_number': phone,
        'person_type': 'coach',
    }


def _today_session(session_id='sess-1', coach_id='coach-1', location_id=None):
    today_str = date.today().strftime('%Y-%m-%d')
    session = {
        'id': session_id,
        'date': today_str,
        'status': 'reminded',
        'coach_ids': [coach_id],
        'coach_id': coach_id,
        'coach_check_ins': {},
    }
    if location_id:
        session['location_id'] = location_id
    return session


def _base_mocks(monkeypatch, coach, sessions):
    monkeypatch.setattr(PersonService, 'resolve', lambda phone: dict(coach))
    monkeypatch.setattr(
        FirebaseService, 'get_all_sessions',
        lambda org_id, coach_id=None, **kw: [dict(s) for s in sessions],
    )
    monkeypatch.setattr(WhatsAppService, 'send_message', lambda **kw: {'success': True})


def test_gps_checkin_no_venue_configured_passes_coach_org_id_to_check_in_session(monkeypatch):
    """Branch: session has no location_id at all -- 'no venue GPS
    configured' path (services/conversation_service.py, was
    check_in_session(..., coach_id=coach_id) with no org_id)."""
    coach = _coach(org_id='org-a', coach_id='coach-1')
    session = _today_session(coach_id='coach-1')  # no location_id
    _base_mocks(monkeypatch, coach, [session])

    calls = []

    def _fake_check_in_session(session_id, check_in_data, org_id, coach_id=None):
        calls.append({'session_id': session_id, 'coach_id': coach_id, 'org_id': org_id})
        return dict(session)

    monkeypatch.setattr(FirebaseService, 'check_in_session', _fake_check_in_session)

    ConversationService.handle_location_check_in('+27821234567', -33.9, 18.4)

    assert len(calls) == 1
    assert calls[0]['org_id'] == 'org-a'
    assert calls[0]['coach_id'] == 'coach-1'


def test_gps_checkin_distance_verified_passes_coach_org_id_to_check_in_session(monkeypatch):
    """Branch: session has a location with coordinates -- 'distance
    verified' path (services/conversation_service.py, was
    check_in_session(..., coach_id=coach_id) with no org_id)."""
    coach = _coach(org_id='org-a', coach_id='coach-1')
    session = _today_session(coach_id='coach-1', location_id='loc-1')
    _base_mocks(monkeypatch, coach, [session])

    monkeypatch.setattr(
        FirebaseService, 'get_location',
        lambda location_id, org_id: (
            {'latitude': -33.9, 'longitude': 18.4, 'radius': 500} if location_id == 'loc-1' else None
        ),
    )

    calls = []

    def _fake_check_in_session(session_id, check_in_data, org_id, coach_id=None):
        calls.append({'session_id': session_id, 'coach_id': coach_id, 'org_id': org_id})
        return dict(session)

    monkeypatch.setattr(FirebaseService, 'check_in_session', _fake_check_in_session)

    ConversationService.handle_location_check_in('+27821234567', -33.9, 18.4)

    assert len(calls) == 1
    assert calls[0]['org_id'] == 'org-a'
    assert calls[0]['coach_id'] == 'coach-1'


def test_check_in_session_does_not_act_on_a_session_from_another_org(monkeypatch):
    """The guarantee the two fixes above now rely on: once check_in_session
    is given the coach's real org_id (instead of the removed None
    default), it must not silently succeed against a session document
    that actually belongs to a different org.

    Exercises the real FirebaseService.check_in_session/get_session
    filtering logic (via a fake Firestore doc), not a mock that assumes
    the filter works.
    """
    other_org_session_doc = {'org_id': 'org-b', 'coach_ids': ['coach-1'], 'status': 'reminded'}

    class _FakeSnapshot:
        exists = True
        id = 'sess-x'

        def to_dict(self):
            return dict(other_org_session_doc)

    class _FakeDocRef:
        def get(self):
            return _FakeSnapshot()

        def update(self, data):
            pass

    class _FakeCollection:
        def document(self, doc_id):
            return _FakeDocRef()

    class _FakeDb:
        def collection(self, name):
            assert name == 'sessions'
            return _FakeCollection()

    monkeypatch.setattr(FirebaseService, 'get_db', lambda: _FakeDb())

    result = FirebaseService.check_in_session(
        'sess-x', {'location_verified': True, 'location': {}},
        org_id='org-a', coach_id='coach-1',
    )

    assert result is None
