"""Unit tests for StorageService.get_signing_credentials() -- the fix for
signed URL generation on Cloud Run (services/storage_service.py).

Root cause this closes: Cloud Run/GCE's default credentials
(google.auth.compute_engine.credentials.Credentials) only ever carry a
bearer token, never a private key -- blob.generate_signed_url() raises
AttributeError on these regardless of IAM permissions granted, because
nothing tells the google-cloud-storage library to sign via IAM instead of a
local private key. get_signing_credentials() wraps the default credentials
in google.auth.impersonated_credentials.Credentials, targeting the SAME
service account (self-impersonation), routing signing through the IAM
signBlob API via the roles/iam.serviceAccountTokenCreator grant already
present on that service account.

These are pure unit tests: google.auth.default() and
impersonated_credentials.Credentials are both monkeypatched (a real signed
URL call needs live GCP IAM, not mockable end-to-end here) -- the point is
to prove the CODE PATH is correct: the right kind of credentials get built,
targeting the right principal and scopes, and the result is cached rather
than rebuilt on every call. See tests/test_end_session_photo_note.py and
tests/test_headcount_attendance.py for the call-site-level proof that
handle_image_message actually passes this through to generate_signed_url().

Usage:
    cd backend
    pytest tests/test_storage_signing_credentials.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) now lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

import pytest  # noqa: E402
import services.storage_service as storage_service_module  # noqa: E402
from services.storage_service import StorageService  # noqa: E402
from google.auth.credentials import Signing  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_signing_credentials_cache():
    StorageService._signing_credentials = None
    yield
    StorageService._signing_credentials = None


class _FakeComputeEngineCredentials:
    """Stands in for google.auth.compute_engine.credentials.Credentials --
    deliberately does NOT implement google.auth.credentials.Signing, same
    as the real thing: only a bearer token, no private key."""

    def __init__(self):
        self.valid = False
        self.refresh_calls = 0
        # Real compute engine credentials report the literal string
        # 'default' until the first refresh() resolves the actual email
        # from the metadata server.
        self.service_account_email = 'default'

    def refresh(self, request):
        self.refresh_calls += 1
        self.valid = True
        self.service_account_email = '218004920355-compute@developer.gserviceaccount.com'


class _FakeSigningCredentials(Signing):
    """Stands in for google.oauth2.service_account.Credentials (a real key
    file) -- already implements Signing, so no impersonation is needed."""

    def sign_bytes(self, message):
        return b'signed'

    @property
    def signer_email(self):
        return 'key-file@teko-236ad.iam.gserviceaccount.com'

    @property
    def signer(self):
        return None


class _FakeImpersonatedCredentials:
    """Records the kwargs it was constructed with, so tests can assert the
    real helper targets the right principal/scopes without needing a live
    IAM signBlob call."""

    def __init__(self, source_credentials, target_principal, target_scopes, lifetime=3600, **kw):
        self.source_credentials = source_credentials
        self.target_principal = target_principal
        self.target_scopes = target_scopes
        self.lifetime = lifetime


# ---------------------------------------------------------------------------
# 1. Compute-engine-style credentials (no private key) get wrapped in
#    impersonated_credentials.Credentials, targeting the SAME service
#    account, resolved to its real email (not the literal 'default').
# ---------------------------------------------------------------------------

def test_wraps_compute_engine_credentials_in_impersonated_credentials(monkeypatch):
    fake_default_creds = _FakeComputeEngineCredentials()
    monkeypatch.setattr(storage_service_module.google.auth, 'default', lambda: (fake_default_creds, 'teko-236ad'))
    monkeypatch.setattr(storage_service_module.impersonated_credentials, 'Credentials', _FakeImpersonatedCredentials)

    result = StorageService.get_signing_credentials()

    assert isinstance(result, _FakeImpersonatedCredentials)
    assert fake_default_creds.refresh_calls == 1, "must refresh once to resolve the real service account email before targeting it"
    assert result.target_principal == '218004920355-compute@developer.gserviceaccount.com', (
        "must target the REAL resolved email, not the literal 'default' string compute-engine "
        "credentials start with before their first refresh"
    )
    assert result.source_credentials is fake_default_creds
    assert result.target_scopes == ['https://www.googleapis.com/auth/cloud-platform']
    assert result.lifetime == 3600


def test_does_not_refresh_already_valid_credentials_again(monkeypatch):
    """If google.auth.default() happens to return already-valid credentials
    (e.g. a token cached from earlier in the same process), don't force an
    unnecessary refresh -- just read the already-resolved email."""
    fake_default_creds = _FakeComputeEngineCredentials()
    fake_default_creds.valid = True
    fake_default_creds.service_account_email = 'already-resolved@teko-236ad.iam.gserviceaccount.com'
    monkeypatch.setattr(storage_service_module.google.auth, 'default', lambda: (fake_default_creds, 'teko-236ad'))
    monkeypatch.setattr(storage_service_module.impersonated_credentials, 'Credentials', _FakeImpersonatedCredentials)

    result = StorageService.get_signing_credentials()

    assert fake_default_creds.refresh_calls == 0
    assert result.target_principal == 'already-resolved@teko-236ad.iam.gserviceaccount.com'


# ---------------------------------------------------------------------------
# 2. Credentials that already implement Signing (e.g. a local service-
#    account key file) are used as-is -- no impersonation attempted.
# ---------------------------------------------------------------------------

def test_credentials_that_already_support_signing_are_used_directly(monkeypatch):
    fake_signing_creds = _FakeSigningCredentials()
    monkeypatch.setattr(storage_service_module.google.auth, 'default', lambda: (fake_signing_creds, 'teko-236ad'))

    called = {'value': False}

    def _boom(*a, **kw):
        called['value'] = True
        raise AssertionError("must not attempt impersonation for credentials that already support signing")

    monkeypatch.setattr(storage_service_module.impersonated_credentials, 'Credentials', _boom)

    result = StorageService.get_signing_credentials()

    assert result is fake_signing_creds
    assert not called['value']


# ---------------------------------------------------------------------------
# 3. Cached at class level -- google.auth.default() is not called again on
#    a second get_signing_credentials() call (a network round trip).
# ---------------------------------------------------------------------------

def test_result_is_cached_not_rebuilt_on_every_call(monkeypatch):
    fake_default_creds = _FakeComputeEngineCredentials()
    default_calls = {'count': 0}

    def _default():
        default_calls['count'] += 1
        return fake_default_creds, 'teko-236ad'

    monkeypatch.setattr(storage_service_module.google.auth, 'default', _default)
    monkeypatch.setattr(storage_service_module.impersonated_credentials, 'Credentials', _FakeImpersonatedCredentials)

    first = StorageService.get_signing_credentials()
    second = StorageService.get_signing_credentials()

    assert default_calls['count'] == 1, "google.auth.default() must only be called once, not on every signed-URL request"
    assert first is second
