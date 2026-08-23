"""Tests for email normalisation in POST /api/auth/login (routes/auth.py).

get_admin_by_email (services/firebase_service.py) performs an exact
Firestore string match with no normalisation of its own -- login() must
lowercase/strip the submitted email before calling it, or a real account
submitted with different casing or surrounding whitespace silently fails to
authenticate (see LOGIN_BUGS_FOUND.md).

Pure unit test: routes.auth.is_rate_limited and FirebaseService are both
monkeypatched, so nothing here touches Firestore. Same convention as
test_login_rate_limiting.py.

Usage:
    cd backend
    pytest tests/test_login_email_normalization.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

import pytest  # noqa: E402
from flask import Flask  # noqa: E402

import routes.auth as auth_module  # noqa: E402
from routes.auth import auth_bp  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.testing = True
    return app.test_client()


@pytest.fixture(autouse=True)
def _no_rate_limiting(monkeypatch):
    monkeypatch.setattr(auth_module, 'is_rate_limited', lambda key, max_count, window_seconds: False)


def test_mixed_case_and_padded_email_authenticates(client, monkeypatch):
    """A stored account's email is always the normalised form (routes/admin.py
    normalises on create/update). A real user retyping the same address with
    different casing and surrounding whitespace must still authenticate --
    not just get a rate-limit key that happens to normalise (that part
    already worked before this fix; the Firestore lookup itself did not)."""
    seen_lookup_emails = []

    def _fake_lookup(email, include_password=False):
        seen_lookup_emails.append(email)
        # Mirrors the exact-match behaviour of the real Firestore query:
        # only ever "found" for the precise normalised string.
        if email == 'tim@catchtrust.org':
            return {
                'id': 'admin-1',
                'email': 'tim@catchtrust.org',
                'name': 'Tim',
                'role': 'location_admin',
                'org_id': 'org-1',
                'status': 'active',
                'password': 'correct-horse-battery-staple',  # legacy plain-text branch
            }
        return None

    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', _fake_lookup)

    resp = client.post('/api/auth/login', json={
        'username': '  Tim@CatchTrust.org  ',
        'password': 'correct-horse-battery-staple',
    })

    body = resp.get_json()
    assert resp.status_code == 200, body
    assert body['token']
    # Proves login() itself normalised the submitted value before calling
    # get_admin_by_email, not that the lookup happened to tolerate it.
    assert seen_lookup_emails == ['tim@catchtrust.org']
