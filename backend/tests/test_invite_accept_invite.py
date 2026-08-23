"""Tests for POST /api/auth/invite and POST /api/auth/accept-invite
(routes/auth.py).

rate_limiter.py's, auth_token_service.py's, and email_service.py's own
correctness are covered in their own test files. This file proves the
ROUTES wire them together correctly -- the main properties being:

  - a location_admin cannot escalate to super_admin, or invite outside
    their own org (structurally impossible: org_id is never read from
    the invite request body at all);
  - accept-invite creates exactly the account the token says to, never
    what the (unauthenticated, attacker-controlled) request body says;
  - accept-invite never overwrites an account that already exists;
  - neither the invite link nor the raw token ever reaches logs.

Mostly pure unit tests: routes.auth's imported names (is_rate_limited,
create_auth_token, consume_auth_token, send_invite_email,
send_welcome_email) and FirebaseService are monkeypatched, so most of
this never touches Firestore or Resend. One test is a deliberate
exception, matching test_forgot_reset_password.py's own
test_reset_password_token_works_once_end_to_end: proving a token "works
once" needs the real create_auth_token/consume_auth_token pair running
against real staging Firestore -- a mock can't faithfully prove the
transaction's single-use guarantee.

Usage:
    cd backend
    pytest tests/test_invite_accept_invite.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) now lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

import logging  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import jwt as _jwt  # noqa: E402
import pytest  # noqa: E402
from flask import Flask  # noqa: E402

import routes.auth as auth_module  # noqa: E402
from routes.auth import auth_bp  # noqa: E402
from config import Config  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
from services.auth_token_service import (  # noqa: E402
    create_auth_token as real_create_auth_token,
    _hash_token,
)


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.testing = True
    return app.test_client()


def _allow_all(monkeypatch):
    monkeypatch.setattr(auth_module, 'is_rate_limited', lambda key, max_count, window_seconds: False)


def _make_token(role, username='inviter@catchtrust.org', org_id='org-1'):
    payload = {
        'username': username,
        'role': role,
        'org_id': org_id,
        'exp': datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return _jwt.encode(payload, Config.SECRET_KEY, algorithm='HS256')


def _auth_header(role, org_id='org-1'):
    return {'Authorization': f'Bearer {_make_token(role, org_id=org_id)}'}


def _invite(client, role_header, body, org_id='org-1'):
    return client.post('/api/auth/invite', headers=_auth_header(role_header, org_id=org_id), json=body)


def _accept(client, token='some-token', first_name='Jo', last_name='Coach', password='longenoughpassword123', extra=None):
    body = {'token': token, 'first_name': first_name, 'last_name': last_name, 'password': password}
    if extra:
        body.update(extra)
    return client.post('/api/auth/accept-invite', json=body)


# ---------------------------------------------------------------------------
# invite
# ---------------------------------------------------------------------------

def test_location_admin_cannot_invite_super_admin(client, monkeypatch):
    _allow_all(monkeypatch)
    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda email: None)

    resp = _invite(client, 'location_admin', {'email': 'new-super@catchtrust.org', 'role': 'super_admin'})

    assert resp.status_code == 403
    assert 'super_admin' in resp.get_json()['error']


def test_super_admin_can_invite_super_admin(client, monkeypatch):
    """Sanity check on the test above: the block is specific to
    location_admin, not a blanket "nobody can invite super_admin"."""
    _allow_all(monkeypatch)
    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda email: None)
    monkeypatch.setattr(auth_module, 'create_auth_token', lambda *a, **kw: 'fake-raw-token')
    monkeypatch.setattr(auth_module, 'send_invite_email', lambda *a, **kw: None)
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: {'id': org_id, 'name': 'CATCH Trust'})

    resp = _invite(client, 'super_admin', {'email': 'new-super@catchtrust.org', 'role': 'super_admin'})

    assert resp.status_code == 200


def test_location_admin_invite_ignores_org_id_in_body_and_uses_own_org(client, monkeypatch):
    """org_id is never read from the request body at all -- a
    location_admin "inviting into another org" isn't rejected, it's
    structurally impossible: the created token always carries the
    inviter's own org_id regardless of what the body contains."""
    _allow_all(monkeypatch)
    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda email: None)
    monkeypatch.setattr(auth_module, 'send_invite_email', lambda *a, **kw: None)
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: {'id': org_id, 'name': 'CATCH Trust'})

    captured = {}

    def _fake_create_token(token_type, subject, expires_in_minutes, extra_fields=None):
        captured['extra_fields'] = extra_fields
        return 'fake-raw-token'

    monkeypatch.setattr(auth_module, 'create_auth_token', _fake_create_token)

    resp = _invite(
        client, 'location_admin',
        {'email': 'new-coach@catchtrust.org', 'role': 'coach', 'org_id': 'someone-elses-org'},
        org_id='the-inviters-real-org',
    )

    assert resp.status_code == 200
    assert captured['extra_fields']['org_id'] == 'the-inviters-real-org'


def test_invalid_role_is_rejected(client, monkeypatch):
    _allow_all(monkeypatch)
    resp = _invite(client, 'super_admin', {'email': 'someone@catchtrust.org', 'role': 'wizard'})
    assert resp.status_code == 400
    assert 'Role must be one of' in resp.get_json()['error']


def test_coach_cannot_reach_invite_at_all(client, monkeypatch):
    _allow_all(monkeypatch)
    resp = _invite(client, 'coach', {'email': 'someone@catchtrust.org', 'role': 'coach'})
    assert resp.status_code == 403


def test_invite_existing_email_returns_identical_response_and_creates_no_token(client, monkeypatch):
    """Non-enumeration: whether the email already has an account must
    not be observable from the response, and no token/email should be
    generated for an address that doesn't need one."""
    _allow_all(monkeypatch)
    token_created = {'v': False}
    email_sent = {'v': False}
    monkeypatch.setattr(auth_module, 'create_auth_token', lambda *a, **kw: (token_created.__setitem__('v', True), 'x')[1])
    monkeypatch.setattr(auth_module, 'send_invite_email', lambda *a, **kw: email_sent.__setitem__('v', True))

    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda email: {'id': 'existing-1', 'email': email})
    resp_existing = _invite(client, 'super_admin', {'email': 'already-here@catchtrust.org', 'role': 'coach'})

    # Checked here, not after the second call below: that call is for a
    # genuinely new email and is *expected* to create a token/send an
    # email, so asserting these stayed False must happen before it runs.
    assert token_created['v'] is False
    assert email_sent['v'] is False

    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda email: None)
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: {'id': org_id, 'name': 'CATCH Trust'})
    resp_new = _invite(client, 'super_admin', {'email': 'brand-new@catchtrust.org', 'role': 'coach'})

    assert resp_existing.status_code == 200
    assert resp_new.status_code == 200
    assert resp_existing.data == resp_new.data
    assert token_created['v'] is True
    assert email_sent['v'] is True


def test_invite_link_never_appears_in_logs_even_when_send_fails(client, monkeypatch, caplog):
    """Pins the same discipline as reset_link_never_appears_in_logs in
    test_forgot_reset_password.py: the except block around
    send_invite_email logs type(e).__name__ only, never
    logger.exception()/str(e)."""
    _allow_all(monkeypatch)
    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda email: None)
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: {'id': org_id, 'name': 'CATCH Trust'})
    monkeypatch.setattr(auth_module, 'create_auth_token', lambda *a, **kw: 'SUPER-SECRET-RAW-TOKEN-abc123')

    def _raise(*a, **kw):
        raise RuntimeError(
            "send failed, payload was https://app.example.com/accept-invite?token=SUPER-SECRET-RAW-TOKEN-abc123"
        )

    monkeypatch.setattr(auth_module, 'send_invite_email', _raise)

    with caplog.at_level(logging.DEBUG):
        resp = _invite(client, 'super_admin', {'email': 'new@catchtrust.org', 'role': 'coach'})

    assert resp.status_code == 200
    assert 'SUPER-SECRET-RAW-TOKEN-abc123' not in caplog.text
    assert 'accept-invite?token=' not in caplog.text


# ---------------------------------------------------------------------------
# accept-invite
# ---------------------------------------------------------------------------

def test_accept_invite_ignores_role_and_org_id_in_payload_favoring_the_token(client, monkeypatch):
    _allow_all(monkeypatch)
    monkeypatch.setattr(
        auth_module, 'consume_auth_token',
        lambda token, expected_type: {'subject': 'invitee@catchtrust.org', 'role': 'coach', 'org_id': 'org-from-token'},
    )
    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda email: None)
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: {'id': org_id, 'name': 'CATCH Trust'})
    monkeypatch.setattr(auth_module, 'send_welcome_email', lambda *a, **kw: None)

    captured = {}
    monkeypatch.setattr(FirebaseService, 'create_admin', lambda data: captured.setdefault('data', data))

    resp = _accept(
        client,
        extra={'role': 'super_admin', 'org_id': 'attacker-chosen-org'},
    )

    assert resp.status_code == 200, resp.get_json()
    assert captured['data']['role'] == 'coach'
    assert captured['data']['org_id'] == 'org-from-token'
    assert captured['data']['email'] == 'invitee@catchtrust.org'


def test_accept_invite_expired_token_rejected(client, monkeypatch):
    _allow_all(monkeypatch)

    def _raise(*a, **kw):
        raise auth_module.TokenExpired('expired')

    monkeypatch.setattr(auth_module, 'consume_auth_token', _raise)
    resp = _accept(client)
    assert resp.status_code == 400
    assert resp.status_code != 401  # would be swallowed by the frontend's global 401 handler


def test_accept_invite_short_password_rejected(client, monkeypatch):
    _allow_all(monkeypatch)
    resp = _accept(client, password='short')
    assert resp.status_code == 400


def test_accept_invite_does_not_overwrite_existing_account(client, monkeypatch):
    """Race: an account for this email was created after the invite was
    sent. The token is consumed either way, but create_admin must never
    be called."""
    _allow_all(monkeypatch)
    monkeypatch.setattr(
        auth_module, 'consume_auth_token',
        lambda token, expected_type: {'subject': 'invitee@catchtrust.org', 'role': 'coach', 'org_id': 'org-1'},
    )
    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda email: {'id': 'already-created', 'email': email})

    create_called = {'v': False}
    monkeypatch.setattr(FirebaseService, 'create_admin', lambda data: create_called.__setitem__('v', True))

    resp = _accept(client)

    assert resp.status_code == 409
    assert create_called['v'] is False


def test_accept_invite_creates_account_matching_the_admin_users_schema(client, monkeypatch):
    _allow_all(monkeypatch)
    monkeypatch.setattr(
        auth_module, 'consume_auth_token',
        lambda token, expected_type: {'subject': 'invitee@catchtrust.org', 'role': 'coach', 'org_id': 'org-1'},
    )
    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda email: None)
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: {'id': org_id, 'name': 'CATCH Trust'})
    monkeypatch.setattr(auth_module, 'send_welcome_email', lambda *a, **kw: None)

    captured = {}
    monkeypatch.setattr(FirebaseService, 'create_admin', lambda data: captured.setdefault('data', data))

    resp = _accept(client, first_name=' Jo ', last_name=' Coach ', password='longenoughpassword123')

    assert resp.status_code == 200
    data = captured['data']
    assert data['email'] == 'invitee@catchtrust.org'
    assert data['first_name'] == 'Jo'
    assert data['last_name'] == 'Coach'
    assert data['role'] == 'coach'
    assert data['org_id'] == 'org-1'
    assert data['status'] == 'active'
    assert data['is_active'] is True
    assert data['password'].startswith('pbkdf2:')


def test_accept_invite_token_works_once_end_to_end(client, monkeypatch):
    """The one test in this file that isn't mocked at the token layer --
    real create_auth_token/consume_auth_token against real staging
    Firestore, same reasoning as
    test_reset_password_token_works_once_end_to_end."""
    _allow_all(monkeypatch)
    email = f'test-invitee-{uuid.uuid4().hex[:8]}@catchtrust.org'
    raw_token = real_create_auth_token('invite', email, 48 * 60, extra_fields={'role': 'coach', 'org_id': 'org-1'})

    monkeypatch.setattr(FirebaseService, 'get_admin_by_email', lambda e: None)
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: {'id': org_id, 'name': 'CATCH Trust'})
    monkeypatch.setattr(auth_module, 'send_welcome_email', lambda *a, **kw: None)

    creates = []
    monkeypatch.setattr(FirebaseService, 'create_admin', lambda data: creates.append(data))

    try:
        resp1 = _accept(client, token=raw_token, password='longenoughpassword123')
        assert resp1.status_code == 200, resp1.get_json()
        assert len(creates) == 1
        assert creates[0]['email'] == email

        resp2 = _accept(client, token=raw_token, password='anotherlongenoughpw')
        assert resp2.status_code == 400
        assert len(creates) == 1  # no second account created
    finally:
        FirebaseService.get_db().collection('auth_tokens').document(_hash_token(raw_token)).delete()
