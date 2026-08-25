"""Tests for POST /api/auth/forgot-password and POST /api/auth/reset-password
(routes/auth.py).

rate_limiter.py's, auth_token_service.py's, and email_service.py's own
correctness are covered in their own test files. This file proves the
ROUTES wire them together correctly -- the main property being that
forgot-password's response can never be used to tell a real email from
a made-up one, and that reset-password never returns a 401 (which the
frontend's shared api.ts helper would swallow before its own
error-message mapping ever ran -- see LOGIN_BUGS_FOUND.md).

Mostly pure unit tests: routes.auth's imported names (is_rate_limited,
create_auth_token, send_password_reset_email) and FirebaseService are
monkeypatched, so most of this never touches Firestore or Resend. One
test is a deliberate exception: proving a token "works once" needs the
real create_auth_token/consume_auth_token pair running against real
staging Firestore, the same reasoning as test_auth_token_service.py --
a mock can't faithfully prove the transaction's single-use guarantee.

Usage:
    cd backend
    pytest tests/test_forgot_reset_password.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) now lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

import logging  # noqa: E402
import uuid  # noqa: E402

import pytest  # noqa: E402
from flask import Flask  # noqa: E402
from werkzeug.security import check_password_hash  # noqa: E402

import routes.auth as auth_module  # noqa: E402
from routes.auth import auth_bp  # noqa: E402
from config import Config  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
from services.auth_token_service import create_auth_token as real_create_auth_token, _hash_token  # noqa: E402


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.testing = True
    return app.test_client()


def _allow_all(monkeypatch):
    monkeypatch.setattr(auth_module, 'is_rate_limited', lambda key, max_count, window_seconds: False)


def _forgot(client, email='someone@catchtrust.org'):
    return client.post('/api/auth/forgot-password', json={'email': email})


def _reset(client, token='some-token', password='longenoughpassword123'):
    return client.post('/api/auth/reset-password', json={'token': token, 'password': password})


# ---------------------------------------------------------------------------
# forgot-password
# ---------------------------------------------------------------------------

def test_unknown_email_returns_the_same_response_as_a_known_one(client, monkeypatch):
    monkeypatch.setattr(Config, 'RESEND_API_KEY', 'fake-key-for-test')
    _allow_all(monkeypatch)
    monkeypatch.setattr(auth_module, 'create_auth_token', lambda *a, **kw: 'fake-raw-token')
    monkeypatch.setattr(auth_module, 'send_password_reset_email', lambda *a, **kw: None)

    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda email: {'id': 'admin-1', 'email': email, 'name': 'Tim'})
    resp_known = _forgot(client, email='tim@catchtrust.org')

    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda email: None)
    resp_unknown = _forgot(client, email='definitely-fake@nowhere.invalid')

    assert resp_known.status_code == 200
    assert resp_unknown.status_code == 200
    assert resp_known.data == resp_unknown.data


def test_forgot_password_rate_limit_fires_before_any_lookup(client, monkeypatch):
    monkeypatch.setattr(Config, 'RESEND_API_KEY', 'fake-key-for-test')
    monkeypatch.setattr(auth_module, 'is_rate_limited', lambda key, max_count, window_seconds: True)
    lookup_called = {'v': False}

    def _fake_lookup(email):
        lookup_called['v'] = True
        return None

    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', _fake_lookup)

    resp = _forgot(client)
    assert resp.status_code == 429
    assert lookup_called['v'] is False


def test_forgot_password_503_when_resend_unconfigured_without_leaking_existence(client, monkeypatch):
    monkeypatch.setattr(Config, 'RESEND_API_KEY', '')
    _allow_all(monkeypatch)
    lookup_called = {'v': False}

    def _fake_lookup(email):
        lookup_called['v'] = True
        return None

    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', _fake_lookup)

    resp = _forgot(client)
    assert resp.status_code == 503
    # Checked before any account-specific work -- fires identically for
    # every email, real or not.
    assert lookup_called['v'] is False


def test_forgot_password_normalises_email_before_lookup(client, monkeypatch):
    monkeypatch.setattr(Config, 'RESEND_API_KEY', 'fake-key-for-test')
    _allow_all(monkeypatch)
    seen = {}

    def _fake_lookup(email):
        seen['email'] = email
        return None

    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', _fake_lookup)

    _forgot(client, email='  Tim@CatchTrust.ORG  ')
    assert seen['email'] == 'tim@catchtrust.org'


def test_forgot_password_link_uses_frontend_url_and_the_raw_token(client, monkeypatch):
    monkeypatch.setattr(Config, 'RESEND_API_KEY', 'fake-key-for-test')
    monkeypatch.setattr(Config, 'FRONTEND_URL', 'https://app.example.com')
    monkeypatch.setattr(Config, 'FRONTEND_BASE_URL', 'https://app.example.com')
    _allow_all(monkeypatch)
    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda email: {'id': 'admin-1', 'email': email, 'name': 'Tim'})
    monkeypatch.setattr(auth_module, 'create_auth_token', lambda token_type, subject, expires_in_minutes: 'RAW-TOKEN-VALUE')

    captured = {}

    def _fake_send(to_email, reset_link, name):
        captured['link'] = reset_link

    monkeypatch.setattr(auth_module, 'send_password_reset_email', _fake_send)

    _forgot(client, email='tim@catchtrust.org')
    assert captured['link'] == 'https://app.example.com/reset-password?token=RAW-TOKEN-VALUE'


def test_reset_link_from_comma_separated_frontend_url_contains_no_comma(client, monkeypatch):
    """Regression test for the bug FRONTEND_BASE_URL was added to fix:
    FRONTEND_URL may be a comma-separated list (app.py's CORS setup splits
    it into an allow-list), but the reset link must be built from a single
    origin -- if routes/auth.py ever reverts to reading Config.FRONTEND_URL
    directly here, this link would contain a comma."""
    monkeypatch.setattr(Config, 'RESEND_API_KEY', 'fake-key-for-test')
    monkeypatch.setattr(Config, 'FRONTEND_URL', 'https://app.useteko.com, https://staging-xyz.run.app')
    monkeypatch.setattr(Config, 'FRONTEND_BASE_URL', 'https://app.useteko.com')
    _allow_all(monkeypatch)
    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda email: {'id': 'admin-1', 'email': email, 'name': 'Tim'})
    monkeypatch.setattr(auth_module, 'create_auth_token', lambda token_type, subject, expires_in_minutes: 'RAW-TOKEN-VALUE')

    captured = {}

    def _fake_send(to_email, reset_link, name):
        captured['link'] = reset_link

    monkeypatch.setattr(auth_module, 'send_password_reset_email', _fake_send)

    _forgot(client, email='tim@catchtrust.org')
    assert ',' not in captured['link']
    assert captured['link'] == 'https://app.useteko.com/reset-password?token=RAW-TOKEN-VALUE'


def test_reset_link_never_appears_in_logs_even_when_send_fails(client, monkeypatch, caplog):
    """Pins the fix applied to routes/auth.py alongside these endpoints:
    the except block around send_password_reset_email logs
    type(e).__name__ only, never logger.exception()/str(e) -- a Resend
    exception can embed the request payload (i.e. the link) in its own
    message, same risk email_service.py's own _send() is hardened
    against."""
    monkeypatch.setattr(Config, 'RESEND_API_KEY', 'fake-key-for-test')
    monkeypatch.setattr(Config, 'FRONTEND_URL', 'https://app.example.com')
    monkeypatch.setattr(Config, 'FRONTEND_BASE_URL', 'https://app.example.com')
    _allow_all(monkeypatch)
    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda email: {'id': 'admin-1', 'email': email, 'name': 'Tim'})
    monkeypatch.setattr(auth_module, 'create_auth_token', lambda *a, **kw: 'SUPER-SECRET-RAW-TOKEN-abc123')

    def _raise(*a, **kw):
        raise RuntimeError(
            "send failed, payload was https://app.example.com/reset-password?token=SUPER-SECRET-RAW-TOKEN-abc123"
        )

    monkeypatch.setattr(auth_module, 'send_password_reset_email', _raise)

    with caplog.at_level(logging.DEBUG):
        resp = _forgot(client, email='tim@catchtrust.org')

    assert resp.status_code == 200
    assert 'SUPER-SECRET-RAW-TOKEN-abc123' not in caplog.text
    assert 'reset-password?token=' not in caplog.text


# ---------------------------------------------------------------------------
# reset-password
# ---------------------------------------------------------------------------

def test_reset_password_short_password_rejected(client, monkeypatch):
    _allow_all(monkeypatch)
    resp = _reset(client, password='short')
    assert resp.status_code == 400


def test_reset_password_rate_limit_fires(client, monkeypatch):
    monkeypatch.setattr(auth_module, 'is_rate_limited', lambda key, max_count, window_seconds: True)
    resp = _reset(client)
    assert resp.status_code == 429


def test_reset_password_expired_token_rejected(client, monkeypatch):
    _allow_all(monkeypatch)

    def _raise(*a, **kw):
        raise auth_module.TokenExpired('expired')

    monkeypatch.setattr(auth_module, 'consume_auth_token', _raise)
    resp = _reset(client)
    assert resp.status_code == 400
    assert resp.status_code != 401  # would be swallowed by the frontend's global 401 handler


def test_reset_password_unknown_token_rejected(client, monkeypatch):
    _allow_all(monkeypatch)

    def _raise(*a, **kw):
        raise auth_module.TokenNotFound('nope')

    monkeypatch.setattr(auth_module, 'consume_auth_token', _raise)
    resp = _reset(client)
    assert resp.status_code == 400


def test_reset_password_already_used_token_rejected(client, monkeypatch):
    _allow_all(monkeypatch)

    def _raise(*a, **kw):
        raise auth_module.TokenAlreadyUsed('used')

    monkeypatch.setattr(auth_module, 'consume_auth_token', _raise)
    resp = _reset(client)
    assert resp.status_code == 400


def test_reset_password_success_hashes_with_pbkdf2_and_updates_the_right_admin(client, monkeypatch):
    _allow_all(monkeypatch)
    monkeypatch.setattr(auth_module, 'consume_auth_token', lambda token, expected_type: {'subject': 'admin-123', 'used': True})

    captured = {}

    def _fake_update(admin_id, data):
        captured['admin_id'] = admin_id
        captured['data'] = data

    monkeypatch.setattr(FirebaseService, 'update_admin', _fake_update)

    resp = _reset(client, password='longenoughpassword123')
    assert resp.status_code == 200
    assert captured['admin_id'] == 'admin-123'
    stored_hash = captured['data']['password']
    assert stored_hash.startswith('pbkdf2:')
    assert check_password_hash(stored_hash, 'longenoughpassword123')


def test_reset_password_token_works_once_end_to_end(client, monkeypatch):
    """The one test in this file that isn't mocked at the token layer --
    real create_auth_token/consume_auth_token against real staging
    Firestore, same reasoning as test_auth_token_service.py: single-use
    is exactly the property not worth taking on faith from a mock."""
    _allow_all(monkeypatch)
    admin_id = f'test-admin-{uuid.uuid4().hex[:8]}'
    raw_token = real_create_auth_token('password_reset', admin_id, 60)

    updates = []
    monkeypatch.setattr(FirebaseService, 'update_admin', lambda aid, data: updates.append((aid, data)))

    try:
        resp1 = _reset(client, token=raw_token, password='longenoughpassword123')
        assert resp1.status_code == 200
        assert len(updates) == 1
        assert updates[0][0] == admin_id

        resp2 = _reset(client, token=raw_token, password='anotherlongenoughpw')
        assert resp2.status_code == 400
        assert len(updates) == 1  # no second write
    finally:
        FirebaseService.get_db().collection('auth_tokens').document(_hash_token(raw_token)).delete()
