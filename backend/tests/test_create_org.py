"""Unit tests for scripts/create_org.py.

Covers the core create_org() function directly (never main()): main() owns
the hardcoded-production-project guard and the ADC connectivity probe,
neither of which should run under pytest (this suite always runs against
teko-staging-tgh -- see tests/conftest.py). create_org() itself is pure
aside from two FirebaseService calls, both monkeypatched here, so nothing
in this file touches real Firestore.

  - refuses (raises OrgCreationError, writes nothing) without a
    safeguarding lead email
  - refuses (raises OrgCreationError, writes nothing) without an admin
  - refuses on a duplicate slug (reports the existing org, writes nothing)
  - writes the full field set -- every org field and every admin field --
    on a clean run

Usage:
    cd backend
    pytest tests/test_create_org.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) now lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

import argparse  # noqa: E402

import pytest  # noqa: E402

from services.firebase_service import FirebaseService  # noqa: E402
from scripts.create_org import create_org, OrgCreationError  # noqa: E402


def _args(**overrides):
    defaults = dict(
        name="Acme FC",
        slug="acme-fc",
        type="sports",
        timezone="Africa/Johannesburg",
        country="South Africa",
        supported_languages=["English", "Afrikaans"],
        works_with_minors=True,
        attendance_mode="named",
        safeguarding_lead_name="Jane Doe",
        safeguarding_lead_email="jane@acmefc.org",
        admin_name="Jane Doe",
        admin_email="jane@acmefc.org",
        admin_role="location_admin",
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.fixture(autouse=True)
def no_existing_org(monkeypatch):
    """By default, no org with the given slug exists yet -- individual
    tests override this to exercise the duplicate-slug path."""
    monkeypatch.setattr(FirebaseService, 'get_organisation_by_slug', lambda slug: None)


def _spy_create_organisation(monkeypatch):
    calls = []

    def _fake(data):
        calls.append(dict(data))
        return {'id': 'new-org-id', **data}

    monkeypatch.setattr(FirebaseService, 'create_organisation', _fake)
    return calls


def _spy_create_admin(monkeypatch):
    calls = []

    def _fake(data):
        calls.append(dict(data))
        return {'id': 'new-admin-id', **data}

    monkeypatch.setattr(FirebaseService, 'create_admin', _fake)
    return calls


def _fail_if_called(monkeypatch, target):
    def _boom(*a, **k):
        raise AssertionError(f"{target} should never be called on a refused request")

    monkeypatch.setattr(FirebaseService, target, _boom)


# ---------------------------------------------------------------------------
# Refuses without a safeguarding lead email
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("email", ["", "   ", None, "not-an-email", "todo@example.com", "lead@test.invalid"])
def test_refuses_without_safeguarding_lead_email(monkeypatch, email):
    _fail_if_called(monkeypatch, 'create_organisation')
    _fail_if_called(monkeypatch, 'create_admin')

    with pytest.raises(OrgCreationError):
        create_org(_args(safeguarding_lead_email=email), commit=True)


def test_accepts_real_safeguarding_lead_email(monkeypatch):
    org_calls = _spy_create_organisation(monkeypatch)
    admin_calls = _spy_create_admin(monkeypatch)

    result = create_org(_args(safeguarding_lead_email="jane@acmefc.org"), commit=True)

    assert result['status'] == 'created'
    assert len(org_calls) == 1
    assert org_calls[0]['safeguarding_lead_email'] == 'jane@acmefc.org'
    assert len(admin_calls) == 1


# ---------------------------------------------------------------------------
# Refuses without an admin
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field,value", [
    ("admin_name", ""),
    ("admin_name", None),
    ("admin_email", ""),
    ("admin_email", None),
    ("admin_role", ""),
    ("admin_role", None),
    ("admin_role", "not-a-real-role"),
])
def test_refuses_without_admin(monkeypatch, field, value):
    _fail_if_called(monkeypatch, 'create_organisation')
    _fail_if_called(monkeypatch, 'create_admin')

    with pytest.raises(OrgCreationError):
        create_org(_args(**{field: value}), commit=True)


# ---------------------------------------------------------------------------
# Refuses on duplicate slug
# ---------------------------------------------------------------------------

def test_refuses_on_duplicate_slug(monkeypatch):
    monkeypatch.setattr(
        FirebaseService, 'get_organisation_by_slug',
        lambda slug: {'id': 'existing-org-id', 'name': 'Already Here', 'slug': slug},
    )
    _fail_if_called(monkeypatch, 'create_organisation')
    _fail_if_called(monkeypatch, 'create_admin')

    result = create_org(_args(), commit=True)

    assert result == {
        'status': 'exists',
        'org_id': 'existing-org-id',
        'org_name': 'Already Here',
    }


def test_duplicate_slug_reported_even_in_dry_run(monkeypatch):
    monkeypatch.setattr(
        FirebaseService, 'get_organisation_by_slug',
        lambda slug: {'id': 'existing-org-id', 'name': 'Already Here', 'slug': slug},
    )
    _fail_if_called(monkeypatch, 'create_organisation')
    _fail_if_called(monkeypatch, 'create_admin')

    result = create_org(_args(), commit=False)

    assert result['status'] == 'exists'


# ---------------------------------------------------------------------------
# Writes the full field set on a clean run
# ---------------------------------------------------------------------------

_EXPECTED_ORG_FIELDS = {
    'name', 'slug', 'type', 'timezone', 'country', 'supported_languages',
    'works_with_minors', 'attendance_mode', 'safeguarding_lead_name',
    'safeguarding_lead_email', 'is_active',
}

_EXPECTED_ADMIN_FIELDS = {
    'name', 'email', 'password', 'role', 'org_id', 'status', 'is_active',
}


def test_writes_full_field_set_on_clean_run(monkeypatch):
    org_calls = _spy_create_organisation(monkeypatch)
    admin_calls = _spy_create_admin(monkeypatch)

    args = _args(
        name="Acme FC",
        slug="acme-fc",
        type="sports",
        timezone="Africa/Johannesburg",
        country="South Africa",
        supported_languages=["English", "Afrikaans"],
        works_with_minors=True,
        attendance_mode="named",
        safeguarding_lead_name="Jane Doe",
        safeguarding_lead_email="jane@acmefc.org",
        admin_name="Jane Doe",
        admin_email="Jane@AcmeFC.org",
        admin_role="location_admin",
    )
    result = create_org(args, commit=True)

    assert result['status'] == 'created'
    assert result['org_id'] == 'new-org-id'
    assert result['admin_id'] == 'new-admin-id'

    assert len(org_calls) == 1
    org_fields = org_calls[0]
    assert set(org_fields.keys()) == _EXPECTED_ORG_FIELDS
    assert org_fields == {
        'name': "Acme FC",
        'slug': "acme-fc",
        'type': "sports",
        'timezone': "Africa/Johannesburg",
        'country': "South Africa",
        'supported_languages': ["English", "Afrikaans"],
        'works_with_minors': True,
        'attendance_mode': "named",
        'safeguarding_lead_name': "Jane Doe",
        'safeguarding_lead_email': "jane@acmefc.org",
        'is_active': True,
    }

    assert len(admin_calls) == 1
    admin_fields = admin_calls[0]
    assert set(admin_fields.keys()) == _EXPECTED_ADMIN_FIELDS
    assert admin_fields['name'] == "Jane Doe"
    # Normalised to lowercase, matching get_admin_by_email()'s exact-match lookup.
    assert admin_fields['email'] == "jane@acmefc.org"
    assert admin_fields['role'] == "location_admin"
    assert admin_fields['org_id'] == "new-org-id"
    assert admin_fields['status'] == "active"
    assert admin_fields['is_active'] is True
    # A real hash was generated, not the plaintext password.
    assert admin_fields['password'].startswith('pbkdf2:sha256:')
    assert admin_fields['password'] != result['admin_password']


def test_dry_run_writes_nothing(monkeypatch):
    _fail_if_called(monkeypatch, 'create_organisation')
    _fail_if_called(monkeypatch, 'create_admin')

    result = create_org(_args(), commit=False)

    assert result['status'] == 'dry_run'
    assert set(result['org_fields'].keys()) == _EXPECTED_ORG_FIELDS
