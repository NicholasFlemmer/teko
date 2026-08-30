"""Unit tests for server-side validation of the org-level `attendance_mode`
field on PUT /api/organisations/<org_id> in routes/organisations.py.

Context: Cricket without Boundaries feature 2 of 5 -- coaches there don't
keep named player registers, so a new attendance_mode field ('named' or
'headcount') controls which /attendance flow ConversationService runs for
that org (see tests/test_headcount_attendance.py for the flow itself).
This file covers only the org-route write validation: exactly 'named' or
'headcount' is accepted, anything else is a 400, and it's writable by both
super_admin and location_admin, matching the other org fields in
_BOTH_ROLES_FIELDS.

Pure unit tests: FirebaseService is stubbed via monkeypatch, tokens are
hand-crafted JWTs run through the real token_required/role_required
decorators via a minimal Flask app registering only organisations_bp --
nothing here touches real Firestore or app.py's module-level
initialization. Mirrors tests/test_org_timezone_validation.py.

Usage:
    cd backend
    pytest tests/test_org_attendance_mode_validation.py -v
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
        ORG_A: {'id': ORG_A, 'name': 'Org A', 'type': 'sports'},
        ORG_B: {'id': ORG_B, 'name': 'Org B', 'type': 'sports'},
    }

    def _get_organisation(org_id):
        return orgs.get(org_id)

    def _update_organisation(org_id, data):
        orgs[org_id] = {**orgs[org_id], **data}
        return orgs[org_id]

    monkeypatch.setattr(FirebaseService, 'get_organisation', _get_organisation)
    monkeypatch.setattr(FirebaseService, 'update_organisation', _update_organisation)

    return app.test_client()


def _make_token(role, org_id, username='test-user'):
    payload = {
        'username': username,
        'role': role,
        'org_id': org_id,
        'exp': datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return _jwt.encode(payload, Config.SECRET_KEY, algorithm='HS256')


def _auth_header(token):
    return {'Authorization': f'Bearer {token}'}


@pytest.mark.parametrize('role', ['super_admin', 'location_admin'])
def test_named_attendance_mode_accepted_and_stored(client, role):
    token = _make_token(role=role, org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={'attendance_mode': 'named'},
    )

    assert resp.status_code == 200
    assert resp.get_json()['organisation']['attendance_mode'] == 'named'


@pytest.mark.parametrize('role', ['super_admin', 'location_admin'])
def test_headcount_attendance_mode_accepted_and_stored(client, role):
    token = _make_token(role=role, org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={'attendance_mode': 'headcount'},
    )

    assert resp.status_code == 200
    assert resp.get_json()['organisation']['attendance_mode'] == 'headcount'


@pytest.mark.parametrize('role', ['super_admin', 'location_admin'])
@pytest.mark.parametrize('bad_value', [
    'both', 'Named', 'HEADCOUNT', '', None, 123, ['named'], {'mode': 'named'},
], ids=['unknown-string', 'wrong-case-named', 'wrong-case-headcount',
        'empty-string', 'null', 'non-string-int', 'non-string-list', 'non-string-dict'])
def test_invalid_attendance_mode_rejected_with_400(client, role, bad_value):
    token = _make_token(role=role, org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={'attendance_mode': bad_value},
    )

    assert resp.status_code == 400
    assert 'attendance_mode' in resp.get_json()['error']
    org = FirebaseService.get_organisation(ORG_A)
    assert org.get('attendance_mode') is None


def test_location_admin_cannot_write_attendance_mode_on_other_org(client, monkeypatch):
    calls = []
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: calls.append(org_id) or {'id': org_id})
    monkeypatch.setattr(FirebaseService, 'update_organisation', lambda org_id, data: calls.append(('write', org_id)) or {})

    token = _make_token(role='location_admin', org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_B}',
        headers=_auth_header(token),
        json={'attendance_mode': 'headcount'},
    )

    assert resp.status_code == 403
    assert calls == [], "FirebaseService must not be consulted for a cross-org request"
