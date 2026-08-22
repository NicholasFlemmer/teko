"""Tests for rate limiting wired into POST /api/auth/login (routes/auth.py).

services/rate_limiter.py's own correctness (atomicity, window reset,
fail-closed) is covered by tests/test_rate_limiter.py against real
staging Firestore. This file only proves the ROUTE wires it correctly:
checked before any Firestore admin lookup, 429 on either the email or IP
limit, and -- the one that matters most here -- the 429 response is
byte-identical whether or not `username` is a real account, so the
response itself can never be used to enumerate valid emails.

Pure unit tests: routes.auth.is_rate_limited and FirebaseService are both
monkeypatched, so nothing here touches Firestore. A minimal Flask app
registers only auth_bp, same convention as test_role_auth.py.

Usage:
    cd backend
    pytest tests/test_login_rate_limiting.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) now lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

import json  # noqa: E402

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


def _login(client, email='someone@catchtrust.org', password='whatever-password'):
    return client.post('/api/auth/login', json={'username': email, 'password': password})


def test_under_limit_reaches_the_admin_lookup(client, monkeypatch):
    monkeypatch.setattr(auth_module, 'is_rate_limited', lambda key, max_count, window_seconds: False)
    lookup_called = {'value': False}

    def _fake_lookup(email, include_password=False):
        lookup_called['value'] = True
        return None

    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', _fake_lookup)

    resp = _login(client)
    assert resp.status_code != 429
    assert lookup_called['value'] is True


def test_over_limit_returns_429_and_never_calls_admin_lookup(client, monkeypatch):
    monkeypatch.setattr(auth_module, 'is_rate_limited', lambda key, max_count, window_seconds: True)
    lookup_called = {'value': False}

    def _fake_lookup(email, include_password=False):
        lookup_called['value'] = True
        return None

    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', _fake_lookup)

    resp = _login(client)
    assert resp.status_code == 429
    # Rate limiting must short-circuit before any Firestore admin lookup --
    # both because there's no reason to spend the read, and because it's
    # what guarantees the response can't vary based on lookup results.
    assert lookup_called['value'] is False


def test_429_response_is_byte_identical_for_real_and_fake_email(client, monkeypatch):
    monkeypatch.setattr(auth_module, 'is_rate_limited', lambda key, max_count, window_seconds: True)

    def _would_have_found_a_real_admin(email, include_password=False):
        # If this ever gets called, the test itself is broken -- rate
        # limiting must have already returned before reaching here. Left
        # in deliberately so a regression that removes the short-circuit
        # shows up as *this* function's return value leaking into the
        # response, not as a silent pass.
        return {'id': 'real-admin-id', 'email': email, 'role': 'location_admin'}

    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', _would_have_found_a_real_admin)
    resp_real_email = _login(client, email='tim@catchtrust.org')

    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda email, include_password=False: None)
    resp_fake_email = _login(client, email='definitely-not-a-real-account@nowhere.invalid')

    assert resp_real_email.status_code == 429
    assert resp_fake_email.status_code == 429
    assert resp_real_email.data == resp_fake_email.data  # byte-identical body
    # Belt-and-suspenders on the actual body content, independent of the
    # raw-bytes comparison above.
    assert json.loads(resp_real_email.data) == json.loads(resp_fake_email.data)


def test_rate_limit_checked_by_both_email_and_ip_keys(client, monkeypatch):
    seen_keys = []

    def _record(key, max_count, window_seconds):
        seen_keys.append(key)
        return False

    monkeypatch.setattr(auth_module, 'is_rate_limited', _record)
    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda email, include_password=False: None)

    _login(client, email='Tim@CatchTrust.org')

    assert any(k.startswith('login:email:') and k.endswith('tim@catchtrust.org') for k in seen_keys), seen_keys
    assert any(k.startswith('login:ip:') for k in seen_keys), seen_keys
