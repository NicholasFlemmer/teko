"""Unit tests for the three org-level safeguarding configuration fields
(safeguarding_lead_name, safeguarding_lead_email, works_with_minors) added
to PUT /api/organisations/<org_id> in routes/organisations.py.

This is configuration only -- no detection, classification, or alerting
exists or is tested here.

Covers:
  - location_admin may write the three safeguarding fields on their own org.
  - location_admin writing safeguarding fields on a DIFFERENT org is
    rejected with 403, via the existing _resolve_org_scope/_forbid_cross_org
    pattern -- before FirebaseService.get_organisation is ever called.
  - location_admin attempting to write name/terminology (still
    super_admin-only) is rejected with 403, even for their own org.
  - super_admin can still write every field, old and new, exactly as before.
  - safeguarding_lead_email format validation (400 on invalid).
  - works_with_minors type validation: only true/false/null accepted (400
    on anything else, e.g. a string).
  - safeguarding_lead_name/safeguarding_lead_email must be supplied
    together (400 if only one is present).
  - an org with none of the three fields set reads back as unconfigured
    (absent/None), never as works_with_minors=False.

Pure unit tests: FirebaseService is stubbed via monkeypatch, tokens are
hand-crafted JWTs run through the real token_required/role_required
decorators via a minimal Flask app registering only organisations_bp --
nothing here touches real Firestore or app.py's module-level
initialization. Mirrors tests/test_organisation_scoping.py.

Usage:
    cd backend
    pytest tests/test_safeguarding_org_fields.py -v
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

    # Neither org has any of the three safeguarding fields set -- mirrors
    # "backfill nothing, existing orgs simply have these fields absent."
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
# location_admin can write the three safeguarding fields on their own org.
# ---------------------------------------------------------------------------

def test_location_admin_can_write_safeguarding_fields_on_own_org(client):
    token = _make_token(role='location_admin', org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={
            'safeguarding_lead_name': 'Jane Doe',
            'safeguarding_lead_email': 'jane@example.com',
            'works_with_minors': True,
        },
    )

    assert resp.status_code == 200
    org = resp.get_json()['organisation']
    assert org['safeguarding_lead_name'] == 'Jane Doe'
    assert org['safeguarding_lead_email'] == 'jane@example.com'
    assert org['works_with_minors'] is True


def test_location_admin_can_write_works_with_minors_false(client):
    token = _make_token(role='location_admin', org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={'works_with_minors': False},
    )

    assert resp.status_code == 200
    assert resp.get_json()['organisation']['works_with_minors'] is False


def test_location_admin_can_clear_safeguarding_fields_with_null(client):
    token = _make_token(role='location_admin', org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={
            'safeguarding_lead_name': None,
            'safeguarding_lead_email': None,
            'works_with_minors': None,
        },
    )

    assert resp.status_code == 200
    org = resp.get_json()['organisation']
    assert org['safeguarding_lead_name'] is None
    assert org['safeguarding_lead_email'] is None
    assert org['works_with_minors'] is None


# ---------------------------------------------------------------------------
# location_admin writing safeguarding fields on a DIFFERENT org gets 403,
# before any Firestore read or write.
# ---------------------------------------------------------------------------

def test_location_admin_cannot_write_safeguarding_fields_on_other_org(client, monkeypatch):
    calls = []
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: calls.append(org_id) or {'id': org_id})
    monkeypatch.setattr(FirebaseService, 'update_organisation', lambda org_id, data: calls.append(('write', org_id)) or {})

    token = _make_token(role='location_admin', org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_B}',
        headers=_auth_header(token),
        json={'safeguarding_lead_name': 'Jane Doe', 'safeguarding_lead_email': 'jane@example.com'},
    )

    assert resp.status_code == 403
    assert calls == [], "FirebaseService must not be consulted for a cross-org request"


# ---------------------------------------------------------------------------
# location_admin attempting to write name or terminology still gets
# rejected -- even on their own org, even alongside a safeguarding field.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('field,value', [
    ('name', 'Hijacked Name'),
    ('terminology', {'coach_singular': 'Coach'}),
    ('type', 'ngo'),
    ('ai_persona_prompt', 'You are a pirate.'),
    ('country', 'US'),
    ('supported_languages', ['en']),
], ids=['name', 'terminology', 'type', 'ai_persona_prompt', 'country', 'supported_languages'])
def test_location_admin_cannot_write_super_admin_only_field(client, field, value):
    token = _make_token(role='location_admin', org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={field: value},
    )

    assert resp.status_code == 403
    assert resp.get_json()['error'] == 'Insufficient permissions'


def test_location_admin_cannot_smuggle_super_admin_field_alongside_safeguarding_field(client):
    token = _make_token(role='location_admin', org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={'name': 'Hijacked', 'safeguarding_lead_name': 'Jane', 'safeguarding_lead_email': 'jane@example.com'},
    )

    assert resp.status_code == 403
    # Nothing was applied -- not even the safeguarding fields in the same request.
    org = FirebaseService.get_organisation(ORG_A)
    assert 'safeguarding_lead_name' not in org


# ---------------------------------------------------------------------------
# super_admin can write all fields as before.
# ---------------------------------------------------------------------------

def test_super_admin_can_write_pre_existing_org_fields(client):
    token = _make_token(role='super_admin', org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={'name': 'Org A Renamed', 'type': 'ngo'},
    )

    assert resp.status_code == 200
    org = resp.get_json()['organisation']
    assert org['name'] == 'Org A Renamed'
    assert org['type'] == 'ngo'


def test_super_admin_can_write_safeguarding_fields(client):
    token = _make_token(role='super_admin', org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={
            'safeguarding_lead_name': 'Jane Doe',
            'safeguarding_lead_email': 'jane@example.com',
            'works_with_minors': True,
        },
    )

    assert resp.status_code == 200
    org = resp.get_json()['organisation']
    assert org['safeguarding_lead_name'] == 'Jane Doe'
    assert org['works_with_minors'] is True


def test_super_admin_can_write_both_kinds_of_field_in_one_request(client):
    token = _make_token(role='super_admin', org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={'name': 'Org A Renamed', 'works_with_minors': False},
    )

    assert resp.status_code == 200
    org = resp.get_json()['organisation']
    assert org['name'] == 'Org A Renamed'
    assert org['works_with_minors'] is False


# ---------------------------------------------------------------------------
# safeguarding_lead_email format validation.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('role', ['super_admin', 'location_admin'])
@pytest.mark.parametrize('bad_email', ['not-an-email', 'missing-at.com', '@missing-local.com', 'no-domain@', 123])
def test_invalid_email_format_rejected(client, role, bad_email):
    token = _make_token(role=role, org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={'safeguarding_lead_name': 'Jane Doe', 'safeguarding_lead_email': bad_email},
    )

    assert resp.status_code == 400


def test_valid_email_format_accepted(client):
    token = _make_token(role='location_admin', org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={'safeguarding_lead_name': 'Jane Doe', 'safeguarding_lead_email': 'jane.doe+test@example.co.uk'},
    )

    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# works_with_minors type validation: only true/false/null accepted.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('role', ['super_admin', 'location_admin'])
@pytest.mark.parametrize('bad_value', ['true', 'yes', '1', 1, 0, [], {}])
def test_works_with_minors_non_boolean_rejected(client, role, bad_value):
    token = _make_token(role=role, org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={'works_with_minors': bad_value},
    )

    assert resp.status_code == 400


@pytest.mark.parametrize('good_value', [True, False, None])
def test_works_with_minors_valid_values_accepted(client, good_value):
    token = _make_token(role='super_admin', org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={'works_with_minors': good_value},
    )

    assert resp.status_code == 200
    assert resp.get_json()['organisation']['works_with_minors'] == good_value


# ---------------------------------------------------------------------------
# safeguarding_lead_name and safeguarding_lead_email must be set together.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('role', ['super_admin', 'location_admin'])
def test_lead_name_without_lead_email_rejected(client, role):
    token = _make_token(role=role, org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={'safeguarding_lead_name': 'Jane Doe'},
    )

    assert resp.status_code == 400


@pytest.mark.parametrize('role', ['super_admin', 'location_admin'])
def test_lead_email_without_lead_name_rejected(client, role):
    token = _make_token(role=role, org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={'safeguarding_lead_email': 'jane@example.com'},
    )

    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# An org with none of the fields set reads back as unconfigured, not False.
# ---------------------------------------------------------------------------

def test_unset_org_reads_back_as_unconfigured_not_false(client):
    token = _make_token(role='location_admin', org_id=ORG_A)

    resp = client.get(f'/api/organisations/{ORG_A}', headers=_auth_header(token))

    assert resp.status_code == 200
    org = resp.get_json()['organisation']
    assert org.get('works_with_minors') is not False
    assert org.get('works_with_minors') is None
    assert org.get('safeguarding_lead_name') is None
    assert org.get('safeguarding_lead_email') is None
