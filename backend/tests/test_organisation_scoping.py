"""Unit tests for the org-scoping fix in routes/organisations.py.

Before this fix, GET /organisations/<org_id>, PUT /organisations/<org_id>,
and GET /organisations/<org_id>/terminology all took org_id straight from
the URL with no check against the caller's own organisation and no role
gate on the write endpoint -- the one route file in the codebase that
didn't use _resolve_org_scope(). Any authenticated user, any role, any
org, could read or write another organisation's record by guessing its id.

This pins the fix:
  - Every affected route now resolves the caller's own org_id via
    _resolve_org_scope() and rejects a URL org_id that doesn't match it.
  - Rejection is always 403, and identical whether or not the URL org_id
    is a real organisation -- FirebaseService.get_organisation is never
    even called for a cross-org request, so there's no existence-based
    branching to leak through response shape or status code.
  - PUT is additionally gated to role_required('super_admin').
  - The intentional super_admin cross-org case (org_id=None, no assigned
    org) still works exactly like every other route file: that caller may
    act on any org_id in the URL.

Pure unit tests: FirebaseService is stubbed via monkeypatch, tokens are
hand-crafted JWTs run through the real token_required/role_required
decorators via a minimal Flask app registering only organisations_bp --
nothing here touches real Firestore or app.py's module-level
initialization.

Usage:
    cd backend
    pytest tests/test_organisation_scoping.py -v
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
from flask import Flask  # noqa: E402

from config import Config  # noqa: E402
from routes.organisations import organisations_bp  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402

ORG_A = 'org-a'
ORG_B = 'org-b'


@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(organisations_bp, url_prefix='/api/organisations')
    app.testing = True

    orgs = {
        ORG_A: {'id': ORG_A, 'name': 'Org A'},
        ORG_B: {'id': ORG_B, 'name': 'Org B'},
    }

    def _get_organisation(org_id):
        return orgs.get(org_id)

    def _get_org_terminology(org_id):
        org = orgs.get(org_id)
        return {'coach_singular': 'Coach'} if org else {}

    def _update_organisation(org_id, data):
        orgs[org_id] = {**orgs[org_id], **data}
        return orgs[org_id]

    monkeypatch.setattr(FirebaseService, 'get_organisation', _get_organisation)
    monkeypatch.setattr(FirebaseService, 'get_org_terminology', _get_org_terminology)
    monkeypatch.setattr(FirebaseService, 'update_organisation', _update_organisation)

    return app.test_client()


def _make_token(role, org_id, include_org_id_claim=True, username='test-user'):
    payload = {
        'username': username,
        'role': role,
        'exp': datetime.now(timezone.utc) + timedelta(hours=1),
    }
    if include_org_id_claim:
        payload['org_id'] = org_id
    return _jwt.encode(payload, Config.SECRET_KEY, algorithm='HS256')


def _auth_header(token):
    return {'Authorization': f'Bearer {token}'}


# ---------------------------------------------------------------------------
# Cannot read another organisation.
# ---------------------------------------------------------------------------

def test_cannot_read_another_organisation(client):
    token = _make_token(role='location_admin', org_id=ORG_A)

    resp = client.get(f'/api/organisations/{ORG_B}', headers=_auth_header(token))

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Cannot write another organisation.
# ---------------------------------------------------------------------------

def test_cannot_write_another_organisation(client):
    token = _make_token(role='super_admin', org_id=ORG_A)

    resp = client.put(f'/api/organisations/{ORG_B}', headers=_auth_header(token), json={'name': 'Hijacked'})

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Terminology cannot be read cross-organisation.
# ---------------------------------------------------------------------------

def test_terminology_cannot_be_read_cross_organisation(client):
    token = _make_token(role='location_admin', org_id=ORG_A)

    resp = client.get(f'/api/organisations/{ORG_B}/terminology', headers=_auth_header(token))

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# The rejection is 403 in every case -- including that it doesn't vary
# based on whether the other organisation actually exists.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('method,path_suffix,body', [
    ('get', '', None),
    ('get', '/terminology', None),
], ids=['get_organisation', 'get_terminology'])
def test_rejection_is_403_regardless_of_target_org_existing(client, monkeypatch, method, path_suffix, body):
    """A cross-org GET for a real other-org id and a cross-org GET for an
    id that doesn't exist at all must be indistinguishable -- same status,
    same body -- and FirebaseService must never even be consulted, so
    there's no existence check to leak through timing or response shape."""
    calls = []
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: calls.append(org_id) or {'id': org_id})
    monkeypatch.setattr(FirebaseService, 'get_org_terminology', lambda org_id: calls.append(org_id) or {'x': 1})

    token = _make_token(role='location_admin', org_id=ORG_A)

    resp_real = getattr(client, method)(f'/api/organisations/{ORG_B}{path_suffix}', headers=_auth_header(token))
    resp_fake = getattr(client, method)(f'/api/organisations/does-not-exist{path_suffix}', headers=_auth_header(token))

    assert resp_real.status_code == 403
    assert resp_fake.status_code == 403
    assert resp_real.get_json() == resp_fake.get_json()
    assert calls == [], "FirebaseService must not be consulted for a cross-org request"


def test_write_rejection_is_403_not_404(client):
    token = _make_token(role='super_admin', org_id=ORG_A)

    resp = client.put('/api/organisations/does-not-exist', headers=_auth_header(token), json={'name': 'X'})

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# A caller can still read and write their own organisation normally.
# ---------------------------------------------------------------------------

def test_can_read_own_organisation(client):
    token = _make_token(role='location_admin', org_id=ORG_A)

    resp = client.get(f'/api/organisations/{ORG_A}', headers=_auth_header(token))

    assert resp.status_code == 200
    assert resp.get_json()['organisation']['id'] == ORG_A


def test_can_read_own_organisation_terminology(client):
    token = _make_token(role='coach', org_id=ORG_A)

    resp = client.get(f'/api/organisations/{ORG_A}/terminology', headers=_auth_header(token))

    assert resp.status_code == 200
    assert resp.get_json()['success'] is True


def test_can_write_own_organisation_as_super_admin(client):
    token = _make_token(role='super_admin', org_id=ORG_A)

    resp = client.put(f'/api/organisations/{ORG_A}', headers=_auth_header(token), json={'name': 'Org A Renamed'})

    assert resp.status_code == 200
    assert resp.get_json()['organisation']['name'] == 'Org A Renamed'


# ---------------------------------------------------------------------------
# The write endpoint's role gate: non-super_admin is denied even for their
# own organisation, independent of the ownership check.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('role', ['location_admin', 'coach'])
def test_write_own_organisation_still_denied_without_super_admin_role(client, role):
    token = _make_token(role=role, org_id=ORG_A)

    resp = client.put(f'/api/organisations/{ORG_A}', headers=_auth_header(token), json={'name': 'X'})

    assert resp.status_code == 403
    assert resp.get_json()['error'] == 'Insufficient permissions'


# ---------------------------------------------------------------------------
# The intentional super_admin cross-org case (no assigned org) still works
# exactly like every other route file's _resolve_org_scope() usage.
# ---------------------------------------------------------------------------

def test_cross_org_super_admin_can_read_any_organisation(client):
    token = _make_token(role='super_admin', org_id=None)

    resp = client.get(f'/api/organisations/{ORG_B}', headers=_auth_header(token))

    assert resp.status_code == 200
    assert resp.get_json()['organisation']['id'] == ORG_B


def test_cross_org_super_admin_can_write_any_organisation(client):
    token = _make_token(role='super_admin', org_id=None)

    resp = client.put(f'/api/organisations/{ORG_B}', headers=_auth_header(token), json={'name': 'Org B Renamed'})

    assert resp.status_code == 200
    assert resp.get_json()['organisation']['name'] == 'Org B Renamed'
