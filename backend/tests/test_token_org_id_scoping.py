"""Unit tests for org_id being stamped onto check_in_tokens at creation and
threaded through the check-in flow instead of the hardcoded None it used to
pass to get_session/get_coach/get_location/check_in_session.

Covers:
  1. create_check_in_token stamps org_id from an already-fetched session
     (never looked up again) -- and never writes an explicit org_id: None
     when the caller doesn't pass one, since absence of the key is what the
     downstream fail-closed check keys on.
  2. The check-in flow (GET/POST /check-in/<token>) passes the token's own
     org_id into get_session/get_coach/get_location/check_in_session,
     instead of the old hardcoded None.
  3. A token with no org_id at all is rejected before any session/coach/
     location lookup ever happens -- not just "the lookup returns None",
     but the lookup is never attempted, proving there's no unscoped read
     to find.

Pure unit tests: FirebaseService is stubbed via monkeypatch, so nothing
here touches Firestore -- same convention as test_check_in.py. A minimal
Flask app registers only sessions_bp, so importing this file never
triggers app.py's module-level FirebaseService.initialize()/scheduler
start.

Usage:
    cd backend
    pytest tests/test_token_org_id_scoping.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) now lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402
from flask import Flask  # noqa: E402

from routes.sessions import sessions_bp  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(sessions_bp, url_prefix='/api/sessions')
    app.testing = True
    return app.test_client()


SESSION = {
    'id': 'sess-1',
    'org_id': 'org-a',
    'date': '2026-08-14',
    'start_time': '15:50',
    'end_time': '16:50',
    'address': '123 Test Street',
    'location_id': 'loc-1',
    'coach_id': 'coach-1',
    'coach_ids': ['coach-1'],
}

COACH = {'name': 'Test Coach'}


def _token_doc(org_id='org-a', used=False, expires_at=None, session_id='sess-1'):
    """org_id=None omits the key entirely -- matches how a pre-fix token
    (and this method's own behavior with no org_id passed) actually looks,
    not an explicit org_id: null."""
    doc = {
        'token': 'tok-1',
        'session_id': session_id,
        'coach_id': 'coach-1',
        'used': used,
        'expires_at': expires_at or (datetime.now(timezone.utc) + timedelta(hours=1)),
    }
    if org_id is not None:
        doc['org_id'] = org_id
    return doc


class _FakeDocRef:
    def __init__(self, captured, key):
        self._captured = captured
        self._key = key

    def set(self, data):
        self._captured[self._key] = data


class _FakeCollection:
    def __init__(self, captured, expected_name, key):
        self._captured = captured
        self._expected_name = expected_name
        self._key = key

    def document(self, doc_id):
        return _FakeDocRef(self._captured, self._key)


def _fake_db_for_check_in_tokens(captured):
    class _FakeDb:
        def collection(self, name):
            assert name == 'check_in_tokens'
            return _FakeCollection(captured, 'check_in_tokens', 'data')
    return _FakeDb()


# ---------------------------------------------------------------------------
# 1. A newly created token carries org_id.
# ---------------------------------------------------------------------------

def test_create_check_in_token_stamps_org_id(monkeypatch):
    captured = {}
    monkeypatch.setattr(FirebaseService, 'get_db', lambda: _fake_db_for_check_in_tokens(captured))

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    FirebaseService.create_check_in_token('tok-1', 'sess-1', expires_at, coach_id='coach-1', org_id='org-a')

    assert captured['data']['org_id'] == 'org-a'
    assert captured['data']['session_id'] == 'sess-1'


def test_create_check_in_token_without_org_id_writes_no_org_id_key(monkeypatch):
    """No call site in the codebase omits org_id anymore, but the method
    still accepts it -- and must not write an explicit org_id: None in that
    case. The downstream fail-closed check keys on the field being absent
    entirely, matching how a real pre-fix token looks; writing a null value
    instead would still be "no org_id", but for the wrong structural
    reason, and is worth pinning explicitly."""
    captured = {}
    monkeypatch.setattr(FirebaseService, 'get_db', lambda: _fake_db_for_check_in_tokens(captured))

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    FirebaseService.create_check_in_token('tok-2', 'sess-1', expires_at)

    assert 'org_id' not in captured['data']


# ---------------------------------------------------------------------------
# 2. The check-in flow uses the token's org_id rather than None.
# ---------------------------------------------------------------------------

def test_check_in_post_passes_token_org_id_not_none(client, monkeypatch):
    calls = {}

    monkeypatch.setattr(FirebaseService, 'get_check_in_token', lambda token: _token_doc(org_id='org-a'))

    def _fake_get_session(session_id, org_id):
        calls['get_session_org_id'] = org_id
        return dict(SESSION)
    monkeypatch.setattr(FirebaseService, 'get_session', _fake_get_session)

    def _fake_get_location(location_id, org_id):
        calls['get_location_org_id'] = org_id
        return None
    monkeypatch.setattr(FirebaseService, 'get_location', _fake_get_location)

    monkeypatch.setattr(FirebaseService, 'mark_token_used', lambda token: True)

    def _fake_check_in_session(session_id, check_in_data, coach_id=None, org_id=None):
        calls['check_in_session_org_id'] = org_id
        return dict(SESSION)
    monkeypatch.setattr(FirebaseService, 'check_in_session', _fake_check_in_session)

    resp = client.post('/api/sessions/check-in/tok-1', json={'location': {'latitude': 1.0, 'longitude': 2.0}})

    assert resp.status_code == 200
    assert calls['get_session_org_id'] == 'org-a'
    assert calls['get_location_org_id'] == 'org-a'
    assert calls['check_in_session_org_id'] == 'org-a'


def test_get_check_in_info_passes_token_org_id_not_none(client, monkeypatch):
    calls = {}

    monkeypatch.setattr(FirebaseService, 'get_check_in_token', lambda token: _token_doc(org_id='org-a'))

    def _fake_get_session(session_id, org_id):
        calls['get_session_org_id'] = org_id
        return dict(SESSION)
    monkeypatch.setattr(FirebaseService, 'get_session', _fake_get_session)

    def _fake_get_coach(coach_id, org_id):
        calls['get_coach_org_id'] = org_id
        return dict(COACH)
    monkeypatch.setattr(FirebaseService, 'get_coach', _fake_get_coach)

    def _fake_get_location(location_id, org_id):
        calls['get_location_org_id'] = org_id
        return None
    monkeypatch.setattr(FirebaseService, 'get_location', _fake_get_location)

    resp = client.get('/api/sessions/check-in/tok-1')

    assert resp.status_code == 200
    assert calls['get_session_org_id'] == 'org-a'
    assert calls['get_coach_org_id'] == 'org-a'
    assert calls['get_location_org_id'] == 'org-a'


# ---------------------------------------------------------------------------
# 3. A token with no org_id does not fall through to an unscoped read.
# ---------------------------------------------------------------------------

def test_check_in_post_with_no_org_id_token_never_calls_get_session(client, monkeypatch):
    monkeypatch.setattr(FirebaseService, 'get_check_in_token', lambda token: _token_doc(org_id=None))

    calls = []
    monkeypatch.setattr(FirebaseService, 'get_session', lambda session_id, org_id: calls.append(org_id) or dict(SESSION))

    resp = client.post('/api/sessions/check-in/tok-1', json={'location': {'latitude': 1.0, 'longitude': 2.0}})

    assert resp.status_code == 404
    assert 'invalid' in resp.get_json()['error'].lower()
    assert calls == [], "get_session must never be called for a token with no org_id"


def test_get_check_in_info_with_no_org_id_token_never_calls_get_session(client, monkeypatch):
    monkeypatch.setattr(FirebaseService, 'get_check_in_token', lambda token: _token_doc(org_id=None))

    calls = []
    monkeypatch.setattr(FirebaseService, 'get_session', lambda session_id, org_id: calls.append(org_id) or dict(SESSION))

    resp = client.get('/api/sessions/check-in/tok-1')

    assert resp.status_code == 404
    assert 'invalid' in resp.get_json()['error'].lower()
    assert calls == [], "get_session must never be called for a token with no org_id"


def test_add_session_photo_via_token_with_no_org_id_token_never_calls_get_session(client, monkeypatch):
    monkeypatch.setattr(FirebaseService, 'get_check_in_token', lambda token: _token_doc(org_id=None))

    calls = []
    monkeypatch.setattr(FirebaseService, 'get_session', lambda session_id, org_id: calls.append(org_id) or dict(SESSION))

    resp = client.post('/api/sessions/check-in/tok-1/photos', json={'url': 'https://example.test/photo.jpg'})

    assert resp.status_code == 404
    assert 'invalid' in resp.get_json()['error'].lower()
    assert calls == [], "get_session must never be called for a token with no org_id"


def test_check_in_post_with_no_org_id_token_never_calls_check_in_session(client, monkeypatch):
    """Belt-and-braces: even if get_session were somehow reached, the
    write path (check_in_session) must not be either."""
    monkeypatch.setattr(FirebaseService, 'get_check_in_token', lambda token: _token_doc(org_id=None))

    calls = []
    monkeypatch.setattr(FirebaseService, 'check_in_session', lambda *a, **kw: calls.append((a, kw)) or dict(SESSION))

    resp = client.post('/api/sessions/check-in/tok-1', json={'location': {'latitude': 1.0, 'longitude': 2.0}})

    assert resp.status_code == 404
    assert calls == [], "check_in_session must never be called for a token with no org_id"
