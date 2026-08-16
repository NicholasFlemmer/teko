"""Unit tests for the admin role vocabulary fix in routes/auth.py.

Pins two things:
1. role_required('super_admin') accepts a token carrying the canonical
   'super_admin' string and rejects one carrying 'coach'.
2. A token with no role claim at all -- or the old pre-fix 'superadmin'
   (no underscore) string -- is denied, not silently defaulted into access.
   Before this fix, both token_required and role_required defaulted a
   missing role to the literal 'admin', which matched nothing in the real
   role_required() calls elsewhere in the app -- but a *coincidental* future
   match was the risk being closed here, not an actual current hole.

Pure unit tests against a minimal Flask app registering a single synthetic
route guarded by @token_required + @role_required('super_admin') directly
from routes.auth -- nothing here touches Firestore or app.py's module-level
initialization.

Usage:
    cd backend
    pytest tests/test_role_auth.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv

STAGING_ENV_PATH = os.path.join(os.path.dirname(__file__), '..', '.env.staging')
if os.path.exists(STAGING_ENV_PATH):
    load_dotenv(dotenv_path=STAGING_ENV_PATH, override=True)
    os.environ['FIREBASE_CREDENTIALS_PATH'] = ''

from datetime import datetime, timedelta, timezone  # noqa: E402

import jwt as _jwt  # noqa: E402
import pytest  # noqa: E402
from flask import Flask, jsonify  # noqa: E402

from config import Config  # noqa: E402
from routes.auth import token_required, role_required  # noqa: E402


@pytest.fixture
def client():
    app = Flask(__name__)

    @app.route('/protected')
    @token_required
    @role_required('super_admin')
    def protected(current_user):
        return jsonify({'ok': True, 'user': current_user})

    @app.route('/admin-allowed')
    @token_required
    @role_required('admin')
    def admin_allowed(current_user):
        return jsonify({'ok': True, 'user': current_user})

    app.testing = True
    return app.test_client()


def _make_token(role=None, include_role_claim=True, username='test-user', expired=False):
    """Mint a JWT the same way auth.py's login()/refresh_token() do.

    include_role_claim=False omits the 'role' key entirely, simulating a
    token minted before the role claim existed or a hand-crafted one.
    """
    payload = {
        'username': username,
        'exp': datetime.now(timezone.utc) + timedelta(hours=(-1 if expired else 1)),
    }
    if include_role_claim:
        payload['role'] = role
    return _jwt.encode(payload, Config.SECRET_KEY, algorithm='HS256')


def _auth_header(token):
    return {'Authorization': f'Bearer {token}'}


def test_super_admin_role_passes_role_required_super_admin(client):
    token = _make_token(role='super_admin')

    resp = client.get('/protected', headers=_auth_header(token))

    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True


def test_coach_role_is_denied_role_required_super_admin(client):
    token = _make_token(role='coach')

    resp = client.get('/protected', headers=_auth_header(token))

    assert resp.status_code == 403
    assert resp.get_json()['error'] == 'Insufficient permissions'


def test_token_with_no_role_claim_at_all_is_denied_not_defaulted(client):
    """The pre-fix code defaulted a missing role claim to the literal string
    'admin' (in both token_required's decode and role_required's fallback),
    and 'admin' was itself a legitimate role_required() literal elsewhere in
    the app (e.g. the old settings endpoint's role_required('superadmin',
    'admin')). So a role-less token could pass a check that allow-lists
    'admin' -- exercise that exact shape here, not just a check that never
    listed 'admin' as allowed in the first place, or the pre/post-fix
    behavior is indistinguishable by coincidence rather than by the fix."""
    token = _make_token(include_role_claim=False)

    resp = client.get('/admin-allowed', headers=_auth_header(token))

    assert resp.status_code == 403
    assert resp.get_json()['error'] == 'Insufficient permissions'


def test_old_superadmin_string_no_underscore_is_denied_pinning_the_fix(client):
    """Pins the vocabulary fix itself: the pre-fix literal 'superadmin'
    (no underscore) must not be treated as equivalent to 'super_admin'."""
    token = _make_token(role='superadmin')

    resp = client.get('/protected', headers=_auth_header(token))

    assert resp.status_code == 403
    assert resp.get_json()['error'] == 'Insufficient permissions'
