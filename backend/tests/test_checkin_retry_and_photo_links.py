"""Tests for two behaviours:

1. WhatsApp location check-in can be retried when the earlier check-in was
   unverified (outside the radius, or no venue GPS); a verified check-in is
   left alone. Each attempt is recorded on the session, last 10 kept.
2. WhatsApp-sent photos get a fresh short-lived signed link from their
   stored path whenever they are loaded; an expired stored link no longer
   matters. Admin-uploaded (public) photos are untouched.

Pure unit tests: Firestore and Cloud Storage are stubbed.

Usage:
    cd backend
    pytest tests/test_checkin_retry_and_photo_links.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from flask import Flask  # noqa: E402

from routes import sessions as sessions_routes  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
from services.person_service import PersonService  # noqa: E402
from services.storage_service import StorageService  # noqa: E402
from services.whatsapp_service import WhatsAppService  # noqa: E402

VENUE = {'latitude': -33.9, 'longitude': 18.4, 'radius': 100}
AT_VENUE = (-33.9, 18.4)
FAR = (-33.91, 18.4)  # roughly 1.1 km south


def _today():
    return date.today().strftime('%Y-%m-%d')


def _session(check_in=None, location_id='loc-1', status='missed'):
    s = {
        'id': 'sess-1', 'date': _today(), 'status': status,
        'coach_ids': ['coach-1'], 'coach_id': 'coach-1',
        'coach_check_ins': {'coach-1': check_in} if check_in is not None else {},
    }
    if location_id:
        s['location_id'] = location_id
    return s


@pytest.fixture
def run(monkeypatch):
    """Returns run(session, lat, lng) -> (check_in_calls, attempts, message)."""
    def _run(session, lat, lng):
        coach = {'id': 'coach-1', 'org_id': 'org-a', 'name': 'Coach A',
                 'phone_number': '0821234567', 'person_type': 'coach'}
        monkeypatch.setattr(PersonService, 'resolve', lambda phone: dict(coach))
        monkeypatch.setattr(FirebaseService, 'get_all_sessions',
                            lambda org_id, coach_id=None, **kw: [dict(session)])
        monkeypatch.setattr(FirebaseService, 'get_org_now', lambda org_id: datetime.now())
        monkeypatch.setattr(FirebaseService, 'get_location',
                            lambda location_id, org_id: dict(VENUE) if location_id == 'loc-1' else None)
        calls, attempts, sent = [], [], {}
        monkeypatch.setattr(FirebaseService, 'check_in_session',
                            lambda session_id, data, org_id, coach_id=None: calls.append(data) or dict(session))
        monkeypatch.setattr(FirebaseService, 'append_check_in_attempt',
                            lambda session_id, attempt, org_id: attempts.append(attempt))
        monkeypatch.setattr(WhatsAppService, 'send_message',
                            lambda phone_number, message_text: sent.update(text=message_text) or {'success': True})
        ConversationService.handle_location_check_in('+27821234567', lat, lng)
        return calls, attempts, sent.get('text', '')
    return _run


# ── Item 1: retry behaviour ──────────────────────────────────────────────

def test_verified_checkin_stays_and_gets_todays_message(run):
    session = _session(check_in={'location_verified': True, 'distance': 12}, status='checked_in')
    calls, attempts, text = run(session, *AT_VENUE)
    assert calls == []
    assert attempts == []
    assert "already checked in" in text


def test_unverified_retry_now_within_radius_becomes_verified(run):
    session = _session(check_in={'location_verified': False, 'distance': 1100})
    calls, attempts, text = run(session, *AT_VENUE)
    assert len(calls) == 1
    assert calls[0]['location_verified'] is True
    assert calls[0]['distance'] < 100
    assert attempts[0]['verified'] is True
    assert "Checked in" in text


def test_unverified_retry_still_outside_updates_distance_and_stays_unverified(run):
    session = _session(check_in={'location_verified': False, 'distance': 5000})
    calls, attempts, text = run(session, *FAR)
    assert len(calls) == 1
    assert calls[0]['location_verified'] is False
    assert 1000 < calls[0]['distance'] < 1300
    assert attempts[0]['verified'] is False
    assert attempts[0]['distance'] == round(calls[0]['distance'])
    # real venue radius (100m) in the message, move closer + share again
    assert "within 100m" in text
    assert "move closer" in text and "share your location again" in text
    # no raw coordinates in the recorded attempt
    assert set(attempts[0]) == {'coach_id', 'time', 'distance', 'verified'}


def test_no_venue_retry_is_accepted_and_stays_unverified(run):
    session = _session(check_in={'location_verified': False}, location_id=None)
    calls, attempts, text = run(session, *AT_VENUE)
    assert len(calls) == 1
    assert calls[0]['location_verified'] is False
    assert calls[0]['location_verifiable'] is False
    assert attempts[0]['verified'] is False and attempts[0]['distance'] is None
    assert "GPS not configured" in text


def test_completed_session_is_not_reopened_by_a_retry(run):
    session = _session(check_in={'location_verified': False}, status='completed')
    calls, attempts, text = run(session, *AT_VENUE)
    assert calls == [] and "already checked in" in text


class _FakeDoc:
    def __init__(self, store): self.store = store
    def update(self, data): self.store.update(data)


class _FakeDb:
    def __init__(self, store): self.store = store
    def collection(self, name): return self
    def document(self, doc_id): return _FakeDoc(self.store)


def test_attempts_are_capped_at_the_last_10(monkeypatch):
    existing = [{'coach_id': 'coach-1', 'time': f't{i}', 'distance': i, 'verified': False} for i in range(10)]
    store = {}
    monkeypatch.setattr(FirebaseService, 'get_session', lambda sid, org_id: {'id': sid, 'check_in_attempts': existing})
    monkeypatch.setattr(FirebaseService, 'get_db', classmethod(lambda cls: _FakeDb(store)))
    FirebaseService.append_check_in_attempt('sess-1', {'coach_id': 'coach-1', 'time': 'new', 'distance': 99, 'verified': True}, 'org-a')
    saved = store['check_in_attempts']
    assert len(saved) == 10
    assert saved[-1]['time'] == 'new'
    assert saved[0]['time'] == 't1'  # oldest dropped


def test_verified_retry_flips_session_to_checked_in(monkeypatch):
    """check_in_session itself: a verified result sets status checked_in."""
    store = {}
    s = {'id': 'sess-1', 'coach_ids': ['coach-1'], 'coach_id': 'coach-1', 'status': 'missed',
         'coach_check_ins': {'coach-1': {'location_verified': False}}}
    monkeypatch.setattr(FirebaseService, 'get_session', lambda sid, org_id: dict(s))
    monkeypatch.setattr(FirebaseService, 'get_db', classmethod(lambda cls: _FakeDb(store)))
    FirebaseService.check_in_session('sess-1', {'location': {'latitude': 1, 'longitude': 2},
                                                'location_verified': True, 'distance': 20},
                                     org_id='org-a', coach_id='coach-1')
    assert store['status'] == 'checked_in'
    assert store['coach_check_ins.coach-1']['distance'] == 20


# ── Item 2: fresh photo links ────────────────────────────────────────────

@pytest.fixture
def signer(monkeypatch):
    calls = []

    def fake_signed(cls, file_path, expiration_minutes=60):
        calls.append((file_path, expiration_minutes))
        return f"https://signed.example/{file_path}?fresh=1"
    monkeypatch.setattr(StorageService, 'get_signed_url', classmethod(fake_signed))
    return calls


def test_whatsapp_photo_gets_fresh_one_hour_link_ignoring_stored_expired_link(signer):
    stored = {'id': 'p1', 'url': 'https://old.example/expired?X-Goog-Expires=604800', 'file_path': 'team_photos/t1/a.jpg'}
    out = StorageService.with_fresh_photo_link(stored)
    assert out['url'] == 'https://signed.example/team_photos/t1/a.jpg?fresh=1'
    assert signer == [('team_photos/t1/a.jpg', 60)]
    assert stored['url'].startswith('https://old.example')  # input not mutated


def test_admin_uploaded_public_photo_is_left_alone(signer):
    stored = {'id': 'p2', 'url': 'https://storage.googleapis.com/b/photos/x.jpg', 'file_path': 'photos/x.jpg'}
    assert StorageService.with_fresh_photo_link(stored) == stored
    assert signer == []


def test_signing_failure_keeps_stored_link(monkeypatch):
    def boom(cls, *a, **k): raise RuntimeError('no signing')
    monkeypatch.setattr(StorageService, 'get_signed_url', classmethod(boom))
    stored = {'url': 'https://old.example/x', 'file_path': 'team_photos/t/a.jpg'}
    assert StorageService.with_fresh_photo_link(stored) == stored


def test_photos_endpoint_and_session_endpoint_serve_fresh_links(monkeypatch, signer):
    session = {'id': 'sess-1', 'org_id': 'org-a',
               'photos': [{'id': 'p1', 'url': 'https://old/expired', 'file_path': 'team_photos/t/a.jpg'},
                          {'id': 'p2', 'url': 'https://public/x', 'file_path': 'photos/x.jpg'}],
               'group_photo': {'url': 'https://old/expired2', 'file_path': 'team_photos/t/b.jpg'}}
    monkeypatch.setattr(FirebaseService, 'get_session', lambda sid, org_id: dict(session))
    monkeypatch.setattr(sessions_routes, '_resolve_org_scope', lambda: ('org-a', None))

    app = Flask(__name__)
    with app.test_request_context():
        body, status = sessions_routes.get_session_photos.__wrapped__({'id': 'u'}, 'sess-1')
        data = body.get_json()
        assert status == 200
        assert data['photos'][0]['url'].endswith('fresh=1')
        assert data['photos'][1]['url'] == 'https://public/x'
        body, status = sessions_routes.get_session.__wrapped__({'id': 'u'}, 'sess-1')
        s = body.get_json()['session']
        assert s['group_photo']['url'].endswith('fresh=1')
        assert s['photos'][0]['url'].endswith('fresh=1')
