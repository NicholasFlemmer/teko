"""Unit tests for the public check-in read path: GET /api/sessions/check-in/<token>.

First test coverage these routes have had. Written after discovering that
every request to this endpoint raised TypeError: can't compare
offset-naive and offset-aware datetimes (expires_at was stripped of
tzinfo, then compared against datetime.now(timezone.utc)) -- i.e. the
route 500'd on every single real check-in link, valid or not.

Pure unit tests: FirebaseService is stubbed via monkeypatch, so nothing
here touches Firestore -- same convention as test_step3c_fixes.py and
test_context_degradation.py. A minimal Flask app registers only
sessions_bp, so importing this file never triggers app.py's module-level
FirebaseService.initialize()/scheduler start.

Usage:
    cd backend
    pytest tests/test_check_in.py -v
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
    'date': '2026-08-14',
    'start_time': '15:50',
    'end_time': '16:50',
    'address': '123 Test Street',
    'location_id': None,
    'coach_id': 'coach-1',
}

COACH = {'name': 'Test Coach'}


def _token_doc(expires_at, used=False, session_id='sess-1', org_id='org-a'):
    """org_id defaults to a real value: since the org_id-on-token-creation
    fix, a token with no org_id at all is rejected before the used/expiry
    checks even run (see test_token_org_id_scoping.py). Pass org_id=None
    explicitly for tests that want to exercise that rejection itself."""
    doc = {
        'token': 'tok-1',
        'session_id': session_id,
        'coach_id': 'coach-1',
        'used': used,
        'expires_at': expires_at,
    }
    if org_id is not None:
        doc['org_id'] = org_id
    return doc


def test_valid_unexpired_token_returns_session_info(client, monkeypatch):
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    monkeypatch.setattr(FirebaseService, 'get_check_in_token', lambda token: _token_doc(future))
    monkeypatch.setattr(FirebaseService, 'get_session', lambda session_id, org_id: dict(SESSION))
    monkeypatch.setattr(FirebaseService, 'get_coach', lambda coach_id, org_id: dict(COACH))

    resp = client.get('/api/sessions/check-in/tok-1')

    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True
    assert body['session']['id'] == 'sess-1'
    assert body['session']['address'] == '123 Test Street'
    assert body['coach']['name'] == 'Test Coach'


def test_expired_token_is_rejected_cleanly_not_a_500(client, monkeypatch):
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    monkeypatch.setattr(FirebaseService, 'get_check_in_token', lambda token: _token_doc(past))

    resp = client.get('/api/sessions/check-in/tok-1')

    assert resp.status_code == 400
    body = resp.get_json()
    assert body['success'] is False
    assert 'expired' in body['error'].lower()


def test_expired_token_with_naive_expires_at_is_also_rejected_cleanly(client, monkeypatch):
    """Regression guard for the fix itself: expires_at should normally come
    back tz-aware from Firestore, but the defensive naive->UTC coercion
    path must also produce a clean 400, not a TypeError, if it ever
    doesn't."""
    naive_past = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None)
    monkeypatch.setattr(FirebaseService, 'get_check_in_token', lambda token: _token_doc(naive_past))

    resp = client.get('/api/sessions/check-in/tok-1')

    assert resp.status_code == 400
    body = resp.get_json()
    assert body['success'] is False
    assert 'expired' in body['error'].lower()


def test_unknown_token_returns_404(client, monkeypatch):
    monkeypatch.setattr(FirebaseService, 'get_check_in_token', lambda token: None)

    resp = client.get('/api/sessions/check-in/does-not-exist')

    assert resp.status_code == 404
    body = resp.get_json()
    assert body['success'] is False
    assert 'invalid' in body['error'].lower()


def test_already_used_token_returns_400(client, monkeypatch):
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    monkeypatch.setattr(FirebaseService, 'get_check_in_token', lambda token: _token_doc(future, used=True))

    resp = client.get('/api/sessions/check-in/tok-1')

    assert resp.status_code == 400
    body = resp.get_json()
    assert body['success'] is False
    assert 'already been used' in body['error'].lower()
