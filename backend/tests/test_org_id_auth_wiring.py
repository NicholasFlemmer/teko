"""Unit tests for wiring org_id into authentication (routes/auth.py).

Before this change, the login JWT carried username/role/exp only, and
g.current_user_org_id was never assigned anywhere in the codebase -- every
_resolve_org_scope() call therefore always resolved org_id to None, which
403'd every non-super_admin request ("Organisation context missing").

This pins the fix:
  1. login() now reads org_id off the caller's admin_users record and
     includes it as a JWT claim.
  2. token_required now reads that claim and assigns g.current_user_org_id,
     alongside how g.current_user_role is already set.
  3. A token with no org_id claim at all is rejected (401) -- fail closed,
     matching the existing posture for a missing role claim -- except for
     super_admin, the one role allowed to operate without an assigned org.
  4. As a direct consequence, a location_admin token now reaches a
     _resolve_org_scope()-gated route that would previously have 403'd it.

Pure unit tests: FirebaseService is stubbed via monkeypatch for the login
test, and org-scoped routes are hit through minimal Flask apps registering
only the relevant blueprint -- nothing here touches real Firestore or
app.py's module-level initialization.

Usage:
    cd backend
    pytest tests/test_org_id_auth_wiring.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) now lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

from datetime import datetime, timedelta, timezone  # noqa: E402

import jwt as _jwt  # noqa: E402
import pytest  # noqa: E402
from flask import Flask, jsonify, g  # noqa: E402

from config import Config  # noqa: E402
from routes.auth import auth_bp, token_required  # noqa: E402
from routes.sessions import sessions_bp  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402


def _make_raw_token(role=None, org_id='not-set', username='test-user',
                     include_role_claim=True, include_org_id_claim=True, expired=False):
    """Hand-craft a JWT without going through login() -- for tests that need
    to control the claim shape directly (e.g. simulating a pre-migration
    token with no org_id key at all).

    org_id='not-set' is a sentinel distinct from None: pass org_id=None
    explicitly to get a real `"org_id": null` claim (the super_admin
    cross-org shape); the default here just avoids accidentally emitting
    that shape when a test doesn't care about the value.
    """
    payload = {
        'username': username,
        'exp': datetime.now(timezone.utc) + timedelta(hours=(-1 if expired else 1)),
    }
    if include_role_claim:
        payload['role'] = role
    if include_org_id_claim:
        payload['org_id'] = None if org_id == 'not-set' else org_id
    return _jwt.encode(payload, Config.SECRET_KEY, algorithm='HS256')


def _auth_header(token):
    return {'Authorization': f'Bearer {token}'}


# ---------------------------------------------------------------------------
# 1. The JWT contains org_id after login.
# ---------------------------------------------------------------------------

@pytest.fixture
def login_client(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.testing = True

    monkeypatch.setattr(
        FirebaseService, 'get_admin_by_email',
        lambda email, include_password=False: {
            'id': 'admin-1',
            'name': 'Loc Admin',
            'email': 'loc@example.com',
            # Plain-text path (legacy, constant-time compare) -- avoids
            # pulling werkzeug's hasher into this test just to match it.
            'password': 'correct-horse-battery-staple',
            'role': 'location_admin',
            'org_id': 'org-xyz',
            'status': 'active',
        } if email == 'loc@example.com' else None,
    )

    return app.test_client()


def test_jwt_contains_org_id_after_login(login_client):
    resp = login_client.post('/api/auth/login', json={
        'username': 'loc@example.com',
        'password': 'correct-horse-battery-staple',
    })

    assert resp.status_code == 200
    token = resp.get_json()['token']
    decoded = _jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
    assert decoded['org_id'] == 'org-xyz'


# ---------------------------------------------------------------------------
# 2. g.current_user_org_id is populated on an authenticated request.
# 3. A token with no org_id claim is rejected.
# ---------------------------------------------------------------------------

@pytest.fixture
def token_required_client():
    app = Flask(__name__)

    @app.route('/whoami')
    @token_required
    def whoami(current_user):
        return jsonify({
            'user': current_user,
            'org_id': getattr(g, 'current_user_org_id', 'UNSET'),
        })

    app.testing = True
    return app.test_client()


def test_current_user_org_id_populated_on_authenticated_request(token_required_client):
    token = _make_raw_token(role='location_admin', org_id='org-xyz')

    resp = token_required_client.get('/whoami', headers=_auth_header(token))

    assert resp.status_code == 200
    assert resp.get_json()['org_id'] == 'org-xyz'


def test_token_with_no_org_id_claim_is_rejected(token_required_client):
    token = _make_raw_token(role='location_admin', include_org_id_claim=False)

    resp = token_required_client.get('/whoami', headers=_auth_header(token))

    assert resp.status_code == 401
    assert 'org_id' in resp.get_json()['error'].lower() or 'organisation' in resp.get_json()['error'].lower()


def test_super_admin_token_with_no_org_id_claim_is_the_one_exception(token_required_client):
    """super_admin is the one role allowed to operate without an assigned
    org -- a token missing org_id entirely must still be accepted for this
    role specifically, with current_user_org_id resolving to None."""
    token = _make_raw_token(role='super_admin', include_org_id_claim=False)

    resp = token_required_client.get('/whoami', headers=_auth_header(token))

    assert resp.status_code == 200
    assert resp.get_json()['org_id'] is None


def test_non_super_admin_token_with_explicit_null_org_id_is_rejected_downstream_not_here(token_required_client):
    """An org_id claim that is present but null (e.g. a location_admin
    whose admin_users record has no assigned org) is NOT the missing-claim
    case -- token_required lets it through (the claim key exists), and
    current_user_org_id resolves to None. It's _resolve_org_scope() further
    down that must then deny it, not token_required."""
    token = _make_raw_token(role='location_admin', org_id=None)

    resp = token_required_client.get('/whoami', headers=_auth_header(token))

    assert resp.status_code == 200
    assert resp.get_json()['org_id'] is None


# ---------------------------------------------------------------------------
# 4. A location_admin can now reach a scoped route that would previously
#    have 403'd them (because g.current_user_org_id was never assigned).
# ---------------------------------------------------------------------------

@pytest.fixture
def sessions_client(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(sessions_bp, url_prefix='/api/sessions')
    app.testing = True

    monkeypatch.setattr(
        FirebaseService, 'get_all_sessions',
        lambda org_id, start_date=None, end_date=None, coach_id=None: [{'id': 's1', 'org_id': org_id}],
    )

    return app.test_client()


def test_location_admin_reaches_previously_403ing_scoped_route(sessions_client):
    token = _make_raw_token(role='location_admin', org_id='org-xyz')

    resp = sessions_client.get('/api/sessions', headers=_auth_header(token))

    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True
    assert body['sessions'] == [{'id': 's1', 'org_id': 'org-xyz'}]


def test_location_admin_with_no_org_id_claim_still_403s_at_resolve_org_scope(sessions_client):
    """Complements the test above: a location_admin token missing org_id
    entirely is denied at token_required (401) before it can even reach
    _resolve_org_scope() -- the fail-closed check in step 3 subsumes the
    pre-existing 403 that _resolve_org_scope() itself would have produced
    for an org_id that resolved to None."""
    token = _make_raw_token(role='location_admin', include_org_id_claim=False)

    resp = sessions_client.get('/api/sessions', headers=_auth_header(token))

    assert resp.status_code == 401
