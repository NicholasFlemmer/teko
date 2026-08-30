"""Unit tests for server-side validation of the org-level `timezone` field
on PUT /api/organisations/<org_id> in routes/organisations.py.

Context: the field used to accept any string unchecked -- a typo silently
fell back to UTC at read time (FirebaseService.get_org_now) with no error
surfaced to whoever saved it, corrupting that org's session date/time data
with no visible signal. This adds a write-time check: only a value present
in zoneinfo.available_timezones(), or null, is accepted. The runtime
fallback for data already stored before this shipped is untouched and not
retested here -- see tests covering FirebaseService.get_org_now directly.

Empty-string choice: normalised to null, not rejected. This matches how
the other nullable org string fields (safeguarding_lead_name,
safeguarding_lead_email) already behave in this same route -- "" is
treated as "not configured", identical to an explicit null or an absent
key (see _normalize_blank_to_none / _is_blank and
tests/test_safeguarding_org_fields.py).

Pure unit tests: FirebaseService is stubbed via monkeypatch, tokens are
hand-crafted JWTs run through the real token_required/role_required
decorators via a minimal Flask app registering only organisations_bp --
nothing here touches real Firestore or app.py's module-level
initialization. Mirrors tests/test_safeguarding_org_fields.py.

Usage:
    cd backend
    pytest tests/test_org_timezone_validation.py -v
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


# ---------------------------------------------------------------------------
# A valid IANA timezone is accepted and stored.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('role', ['super_admin', 'location_admin'])
def test_valid_timezone_accepted_and_stored(client, role):
    token = _make_token(role=role, org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={'timezone': 'Africa/Johannesburg'},
    )

    assert resp.status_code == 200
    assert resp.get_json()['organisation']['timezone'] == 'Africa/Johannesburg'


# ---------------------------------------------------------------------------
# null is accepted and clears the field.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('role', ['super_admin', 'location_admin'])
def test_null_timezone_accepted_and_clears_field(client, role):
    token = _make_token(role=role, org_id=ORG_A)

    # First set a real value, then clear it.
    client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={'timezone': 'Africa/Johannesburg'},
    )

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={'timezone': None},
    )

    assert resp.status_code == 200
    assert resp.get_json()['organisation']['timezone'] is None


# ---------------------------------------------------------------------------
# An invalid string is rejected with 400 and the field is not written.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('role', ['super_admin', 'location_admin'])
@pytest.mark.parametrize('bad_value', [
    'Not/A/Real/Zone',
    'Africa/Jozi',  # plausible typo of Africa/Johannesburg
    'UTC+2',
    'sast',
    123,
    ['Africa/Johannesburg'],
], ids=['bogus-zone', 'typo', 'utc-offset-string', 'lowercase-abbrev', 'non-string-int', 'non-string-list'])
def test_invalid_timezone_rejected_and_not_written(client, role, bad_value):
    token = _make_token(role=role, org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={'timezone': bad_value},
    )

    assert resp.status_code == 400
    assert 'timezone' in resp.get_json()['error']
    org = FirebaseService.get_organisation(ORG_A)
    assert org.get('timezone') is None


# ---------------------------------------------------------------------------
# Empty string: normalised to null (chosen to match the existing behaviour
# of safeguarding_lead_name / safeguarding_lead_email in this same route,
# where "" is treated identically to null -- see module docstring).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('role', ['super_admin', 'location_admin'])
def test_empty_string_timezone_normalised_to_null(client, role):
    token = _make_token(role=role, org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={'timezone': ''},
    )

    assert resp.status_code == 200
    org = resp.get_json()['organisation']
    assert org['timezone'] is None
    assert org['timezone'] != ''


# ---------------------------------------------------------------------------
# location_admin can write timezone on their own org, not on another org.
# ---------------------------------------------------------------------------

def test_location_admin_can_write_timezone_on_own_org(client):
    token = _make_token(role='location_admin', org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={'timezone': 'America/Sao_Paulo'},
    )

    assert resp.status_code == 200
    assert resp.get_json()['organisation']['timezone'] == 'America/Sao_Paulo'


def test_location_admin_cannot_write_timezone_on_other_org(client, monkeypatch):
    calls = []
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: calls.append(org_id) or {'id': org_id})
    monkeypatch.setattr(FirebaseService, 'update_organisation', lambda org_id, data: calls.append(('write', org_id)) or {})

    token = _make_token(role='location_admin', org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_B}',
        headers=_auth_header(token),
        json={'timezone': 'America/Sao_Paulo'},
    )

    assert resp.status_code == 403
    assert calls == [], "FirebaseService must not be consulted for a cross-org request"
