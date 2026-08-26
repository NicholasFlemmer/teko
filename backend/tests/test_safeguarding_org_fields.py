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


# ---------------------------------------------------------------------------
# Production bug regression: the pair check used to compare key PRESENCE
# ('field' in data), not the field's VALUE.
#
# The exact mechanism that shipped the partial record to production: the
# real OrgSettings.tsx save handler sends `trimmedName || null` for a
# blank field -- an explicit null, not "". The old pairing check
# (`'field' in data`) treated a present-but-null key as "set," so
# name="Ricki" + email=None passed the pair check as "both present." The
# email-format guard was `if has_lead_email and value is not None`, so an
# explicit None short-circuited it too (None is not "not None"). Nothing
# ever validated the email, and the partial record saved with a 200.
#
# A raw API caller (Postman/curl, or a stale/different frontend build)
# could hit the same gap with a literal "" instead of null -- "" was
# actually already caught by the old code's `is not None` guard feeding
# the regex (`_EMAIL_RE.match("")` fails), which is a narrower miss than
# the task description's "empty string is falsy" framing suggests. Both
# variants are tested below since both are real attack shapes; the fix
# (value-based blank check) closes both identically, treating "", null,
# and a missing key the same way throughout.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('role', ['super_admin', 'location_admin'])
def test_actual_production_incident_shape_name_set_email_explicit_null_rejected(client, role):
    """The exact payload the real frontend sends for "lead name filled,
    lead email left blank": trimmedEmail || null resolves to a literal
    None, not "". This is the payload that actually produced the partial
    record in production -- verified to return 200 against the
    unpatched route before this fix (see conversation record)."""
    token = _make_token(role=role, org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={
            'safeguarding_lead_name': 'Ricki',
            'safeguarding_lead_email': None,
        },
    )

    assert resp.status_code == 400
    org = FirebaseService.get_organisation(ORG_A)
    assert org.get('safeguarding_lead_name') is None


@pytest.mark.parametrize('role', ['super_admin', 'location_admin'])
def test_frontend_shaped_payload_name_set_email_empty_string_rejected(client, role):
    """A raw API caller sending literal "" instead of null for the blank
    field -- must be a 400, not a silent partial save, exactly like the
    null variant above."""
    token = _make_token(role=role, org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={
            'safeguarding_lead_name': 'Ricki',
            'safeguarding_lead_email': '',
            'works_with_minors': None,
        },
    )

    assert resp.status_code == 400
    # And nothing was written -- not even the name half of the pair.
    org = FirebaseService.get_organisation(ORG_A)
    assert org.get('safeguarding_lead_name') is None


@pytest.mark.parametrize('role', ['super_admin', 'location_admin'])
def test_frontend_shaped_payload_email_set_name_empty_string_rejected(client, role):
    """Mirror case: email populated, name sent as "" (not omitted)."""
    token = _make_token(role=role, org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={
            'safeguarding_lead_name': '',
            'safeguarding_lead_email': 'jane@example.com',
            'works_with_minors': None,
        },
    )

    assert resp.status_code == 400
    org = FirebaseService.get_organisation(ORG_A)
    assert org.get('safeguarding_lead_email') is None


@pytest.mark.parametrize('role', ['super_admin', 'location_admin'])
def test_frontend_shaped_payload_both_empty_strings_succeeds_and_stores_as_none(client, role):
    """Both blank ("" for both) is the valid "not configured" case -- must
    succeed, and must never persist "" to Firestore, only None."""
    token = _make_token(role=role, org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={
            'safeguarding_lead_name': '',
            'safeguarding_lead_email': '',
            'works_with_minors': None,
        },
    )

    assert resp.status_code == 200
    org = resp.get_json()['organisation']
    assert org['safeguarding_lead_name'] is None
    assert org['safeguarding_lead_email'] is None
    assert org['safeguarding_lead_name'] != ''
    assert org['safeguarding_lead_email'] != ''


@pytest.mark.parametrize('role', ['super_admin', 'location_admin'])
def test_frontend_shaped_payload_whitespace_only_treated_as_empty(client, role):
    """"   " (whitespace-only) must be treated identically to "" -- after
    trimming, both sides are blank, so this is the valid "not configured"
    case, not a mismatched pair."""
    token = _make_token(role=role, org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={
            'safeguarding_lead_name': '   ',
            'safeguarding_lead_email': '  \t ',
            'works_with_minors': None,
        },
    )

    assert resp.status_code == 200
    org = resp.get_json()['organisation']
    assert org['safeguarding_lead_name'] is None
    assert org['safeguarding_lead_email'] is None


@pytest.mark.parametrize('role', ['super_admin', 'location_admin'])
def test_works_with_minors_empty_string_rejected_with_400(client, role):
    """Audit requested alongside the pair-check fix: confirm "" never
    becomes a stored value for works_with_minors either.

    Implemented behaviour: 400, not stored-as-null. isinstance("", bool)
    is False (an empty string is not a bool), so the existing type check
    already rejects "" outright -- it never reaches Firestore in any
    form, blank or otherwise. This test pins that behaviour explicitly
    rather than leaving it as an accidental side effect of the type
    check."""
    token = _make_token(role=role, org_id=ORG_A)

    resp = client.put(
        f'/api/organisations/{ORG_A}',
        headers=_auth_header(token),
        json={'works_with_minors': ''},
    )

    assert resp.status_code == 400
    org = FirebaseService.get_organisation(ORG_A)
    assert org.get('works_with_minors') is None


@pytest.mark.parametrize('role', ['super_admin', 'location_admin'])
def test_frontend_shaped_payload_all_three_populated_succeeds(client, role):
    """All three fields populated with real values, sent exactly as the
    frontend sends them (every key present) -- must succeed."""
    token = _make_token(role=role, org_id=ORG_A)

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
