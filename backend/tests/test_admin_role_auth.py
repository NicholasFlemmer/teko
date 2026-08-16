"""Unit tests for the admin.py role vocabulary repair.

Before this fix, admin.py's five @role_required(...) decorators checked for
the literal 'superadmin' (no underscore), but the real Firestore admin_users
role values are 'super_admin' / 'location_admin' / 'coach' -- so every real
account, including both accounts that hold 'super_admin', got 403'd on every
one of these five routes. This pins the repair: a super_admin token now
reaches all five, while coach and location_admin tokens -- which never had
access and still shouldn't -- remain denied.

It also pins the allowed_roles fix on POST /users: the create-admin body's
'role' field must accept the canonical 'super_admin' and reject the old,
now-meaningless 'superadmin' string.

Pure unit tests: FirebaseService is stubbed via monkeypatch, so nothing here
touches Firestore. A minimal Flask app registers only admin_bp, so importing
this file never triggers app.py's module-level FirebaseService.initialize()/
scheduler start.

Usage:
    cd backend
    pytest tests/test_admin_role_auth.py -v
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
from flask import Flask  # noqa: E402

from config import Config  # noqa: E402
from routes.admin import admin_bp  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(admin_bp, url_prefix='/api/admin')
    app.testing = True

    # Stub every FirebaseService call the five routes touch so a request
    # that gets past the role check succeeds cleanly (200/201), making
    # "reached the route" and "denied at the role check" unambiguous.
    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda email, include_password=False: None)
    monkeypatch.setattr(FirebaseService, 'create_admin', lambda data: {'id': 'new-admin', **data})
    monkeypatch.setattr(FirebaseService, 'get_admin', lambda admin_id: {'id': admin_id, 'name': 'X', 'email': 'x@example.com', 'role': 'coach', 'status': 'active'})
    monkeypatch.setattr(FirebaseService, 'update_admin', lambda admin_id, data: {'id': admin_id, **data})
    monkeypatch.setattr(FirebaseService, 'delete_admin', lambda admin_id: True)
    monkeypatch.setattr(FirebaseService, 'update_settings', lambda data: data)

    return app.test_client()


def _make_token(role, username='test-user'):
    payload = {
        'username': username,
        'role': role,
        'exp': datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return _jwt.encode(payload, Config.SECRET_KEY, algorithm='HS256')


def _auth_header(role):
    return {'Authorization': f'Bearer {_make_token(role)}'}


# The five previously-broken routes, as (method, path, json_body).
FIVE_ROUTES = [
    ('POST', '/api/admin/users', {'name': 'New Admin', 'email': 'new@example.com', 'password': 'password123', 'role': 'coach'}),
    ('PUT', '/api/admin/users/admin-1', {'name': 'Updated Name'}),
    ('DELETE', '/api/admin/users/admin-1', None),
    ('PUT', '/api/admin/users/admin-1/toggle-status', None),
    ('PUT', '/api/admin/settings', {'maintenance_mode': True}),
]
ROUTE_IDS = ['create_admin_user', 'update_admin_user', 'delete_admin_user', 'toggle_admin_status', 'update_settings']


@pytest.mark.parametrize('method,path,body', FIVE_ROUTES, ids=ROUTE_IDS)
def test_super_admin_token_reaches_the_route(client, method, path, body):
    resp = client.open(path, method=method, headers=_auth_header('super_admin'), json=body)

    assert resp.status_code != 403, f'{method} {path} returned {resp.status_code}: {resp.get_json()}'


@pytest.mark.parametrize('method,path,body', FIVE_ROUTES, ids=ROUTE_IDS)
def test_coach_token_is_denied_the_route(client, method, path, body):
    resp = client.open(path, method=method, headers=_auth_header('coach'), json=body)

    assert resp.status_code == 403
    assert resp.get_json()['error'] == 'Insufficient permissions'


@pytest.mark.parametrize('method,path,body', FIVE_ROUTES, ids=ROUTE_IDS)
def test_location_admin_token_is_denied_the_route(client, method, path, body):
    resp = client.open(path, method=method, headers=_auth_header('location_admin'), json=body)

    assert resp.status_code == 403
    assert resp.get_json()['error'] == 'Insufficient permissions'


def test_creating_admin_with_role_super_admin_passes_validation(client):
    body = {'name': 'New Super', 'email': 'newsuper@example.com', 'password': 'password123', 'role': 'super_admin'}

    resp = client.post('/api/admin/users', headers=_auth_header('super_admin'), json=body)

    assert resp.status_code == 201, resp.get_json()


def test_creating_admin_with_old_superadmin_string_fails_validation(client):
    """Pins the vocabulary fix on the body-role validation itself: the old,
    no-underscore literal must not be accepted as a creatable role."""
    body = {'name': 'New Super', 'email': 'newsuper2@example.com', 'password': 'password123', 'role': 'superadmin'}

    resp = client.post('/api/admin/users', headers=_auth_header('super_admin'), json=body)

    assert resp.status_code == 400
    assert 'Role must be one of' in resp.get_json()['error']
