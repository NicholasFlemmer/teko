"""Tests for rate limiting wired into POST /api/auth/login (routes/auth.py).

services/rate_limiter.py's own correctness (atomicity, window reset,
fail-closed) is covered by tests/test_rate_limiter.py against real
staging Firestore. get_trusted_client_ip()'s own correctness is covered
by tests/test_request_ip.py. This file proves the ROUTE wires both
correctly: checked before any Firestore admin lookup, 429 on either the
email or IP limit, the 429 response is byte-identical whether or not
`username` is a real account, and -- the actual bug this was written to
pin -- a forged X-Forwarded-For first entry does NOT change the IP
rate-limit key.

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


def _login(client, email='someone@catchtrust.org', password='whatever-password', headers=None):
    return client.post('/api/auth/login', json={'username': email, 'password': password}, headers=headers)


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


def test_forged_xff_first_entry_does_not_change_the_ip_rate_limit_key(client, monkeypatch):
    """The actual bug: taking XFF[0] gave an attacker a fresh IP key on
    every request, so the IP limit never fired. Sends several requests
    with different forged first entries but the same real client IP at
    index -2 (a different email each time, so only the IP key can trip
    the limit), against a real in-memory counter keyed exactly the way
    is_rate_limited is -- proving both that every request lands on the
    identical key, and that the limit still fires against it."""
    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda email, include_password=False: None)

    real_ip = '203.0.113.5'
    gfe_ip = '169.254.1.1'
    forged_prefixes = ['1.1.1.1', '2.2.2.2', '3.3.3.3', '4.4.4.4']
    MAX = 2

    counts = {}

    def _fake_is_rate_limited(key, max_count, window_seconds):
        # Deliberately ignores the route's real max_count (20 for the IP
        # key) and uses a small fixed threshold instead -- this test is
        # about whether requests land on the SAME key, not about
        # reproducing the production limit values.
        counts[key] = counts.get(key, 0) + 1
        return counts[key] > MAX

    monkeypatch.setattr(auth_module, 'is_rate_limited', _fake_is_rate_limited)

    responses = []
    for i, forged in enumerate(forged_prefixes):
        headers = {'X-Forwarded-For': f'{forged},{real_ip},{gfe_ip}'}
        responses.append(_login(client, email=f'user{i}@catchtrust.org', headers=headers))

    ip_keys = {k for k in counts if k.startswith('login:ip:')}
    assert ip_keys == {f'login:ip:{real_ip}'}, (
        f"expected exactly one shared IP key regardless of the forged first entry, got {ip_keys}"
    )
    assert counts[f'login:ip:{real_ip}'] == len(forged_prefixes)

    # First MAX requests pass the IP check; the rest, same shared key, 429.
    assert responses[0].status_code != 429
    assert responses[1].status_code != 429
    assert responses[2].status_code == 429
    assert responses[3].status_code == 429


def test_no_client_supplied_header_uses_the_lone_google_appended_pair(client, monkeypatch):
    seen_keys = []

    def _record(key, max_count, window_seconds):
        seen_keys.append(key)
        return False

    monkeypatch.setattr(auth_module, 'is_rate_limited', _record)
    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda email, include_password=False: None)

    # No X-Forwarded-For at all -- e.g. Werkzeug's test client hitting the
    # route directly with no header set.
    _login(client)

    ip_keys = [k for k in seen_keys if k.startswith('login:ip:')]
    assert len(ip_keys) == 1
    assert ip_keys[0] != 'login:ip:'  # resolved to *something*, not an empty client_ip


def test_short_xff_header_does_not_use_its_lone_attacker_suppliable_entry(client, monkeypatch):
    seen_keys = []

    def _record(key, max_count, window_seconds):
        seen_keys.append(key)
        return False

    monkeypatch.setattr(auth_module, 'is_rate_limited', _record)
    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda email, include_password=False: None)

    _login(client, headers={'X-Forwarded-For': '1.2.3.4'})

    ip_keys = [k for k in seen_keys if k.startswith('login:ip:')]
    assert len(ip_keys) == 1
    assert ip_keys[0] != 'login:ip:1.2.3.4'


def test_email_keyed_limit_is_unaffected_by_xff_forgery(client, monkeypatch):
    """The email key must depend only on the submitted email, never on
    anything IP/header-related -- forging X-Forwarded-For must not let
    an attacker dodge the per-email limit either."""
    seen_email_keys = []

    def _record(key, max_count, window_seconds):
        if key.startswith('login:email:'):
            seen_email_keys.append(key)
        return False

    monkeypatch.setattr(auth_module, 'is_rate_limited', _record)
    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda email, include_password=False: None)

    for forged in ['1.1.1.1', '9.9.9.9', 'garbage']:
        _login(client, email='tim@catchtrust.org', headers={'X-Forwarded-For': f'{forged},203.0.113.5,169.254.1.1'})

    assert seen_email_keys == ['login:email:tim@catchtrust.org'] * 3
