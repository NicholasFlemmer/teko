"""Tests for email_service.py's fail-closed behaviour.

Pins two things:
  - _send() raises (never returns silently) when RESEND_API_KEY is unset,
    and again when the Resend API call itself fails -- a caller must never
    be able to treat an email that was never sent as delivered.
  - The invite/reset/login link (and anything derived from it) is never
    written to logs, at any log level, under any condition -- not on the
    unconfigured path, and not via a Resend exception's own message, which
    can embed the request payload (i.e. the link) in its str().

Pure unit tests: Config.RESEND_API_KEY and resend.Emails.send are
monkeypatched. Nothing here touches Firestore or sends a real email.

Usage:
    cd backend
    pytest tests/test_email_service.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) now lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

import logging  # noqa: E402

import pytest  # noqa: E402

from config import Config  # noqa: E402
from services import email_service  # noqa: E402
from services.email_service import (  # noqa: E402
    EmailNotConfiguredError,
    send_invite_email,
    send_password_reset_email,
    send_welcome_email,
)

RESET_LINK = "https://app.tekohq.com/reset-password?token=SUPER-SECRET-RESET-TOKEN-abc123"
INVITE_LINK = "https://app.tekohq.com/accept-invite?token=SUPER-SECRET-INVITE-TOKEN-xyz789"
LOGIN_URL = "https://app.tekohq.com/login?token=SUPER-SECRET-LOGIN-TOKEN-qqq111"


# ---------------------------------------------------------------------------
# Unconfigured (RESEND_API_KEY unset): must raise, must never log the link
# ---------------------------------------------------------------------------

def test_send_password_reset_email_raises_when_unconfigured(monkeypatch):
    monkeypatch.setattr(Config, "RESEND_API_KEY", "")
    with pytest.raises(EmailNotConfiguredError):
        send_password_reset_email("tim@catchtrust.org", RESET_LINK, "Tim")


def test_send_password_reset_email_unconfigured_leaks_no_link_in_logs(monkeypatch, caplog):
    monkeypatch.setattr(Config, "RESEND_API_KEY", "")
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(EmailNotConfiguredError):
            send_password_reset_email("tim@catchtrust.org", RESET_LINK, "Tim")

    assert RESET_LINK not in caplog.text
    assert "SUPER-SECRET-RESET-TOKEN" not in caplog.text


def test_send_invite_email_unconfigured_raises_and_leaks_no_link(monkeypatch, caplog):
    monkeypatch.setattr(Config, "RESEND_API_KEY", "")
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(EmailNotConfiguredError):
            send_invite_email("tim@catchtrust.org", INVITE_LINK, "CATCH Trust", "Ricki", "location_admin")

    assert INVITE_LINK not in caplog.text
    assert "SUPER-SECRET-INVITE-TOKEN" not in caplog.text


def test_send_welcome_email_unconfigured_raises_and_leaks_no_link(monkeypatch, caplog):
    monkeypatch.setattr(Config, "RESEND_API_KEY", "")
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(EmailNotConfiguredError):
            send_welcome_email("tim@catchtrust.org", "Tim", "CATCH Trust", LOGIN_URL)

    assert LOGIN_URL not in caplog.text
    assert "SUPER-SECRET-LOGIN-TOKEN" not in caplog.text


# ---------------------------------------------------------------------------
# Resend call fails: must propagate, must never log the link
# ---------------------------------------------------------------------------

def test_resend_failure_propagates_and_leaks_no_link_in_logs(monkeypatch, caplog):
    monkeypatch.setattr(Config, "RESEND_API_KEY", "fake-key-for-test")

    class _BoomError(Exception):
        pass

    def _raise(*args, **kwargs):
        # A real Resend SDK exception can embed the request payload -- i.e.
        # the html body, i.e. the link -- in its own message. Proves _send()
        # never formats str(e) into a log line, not just that it avoids its
        # own fallback_detail.
        raise _BoomError(f"Resend API error, payload was: {{'html': '...{RESET_LINK}...'}}")

    monkeypatch.setattr(email_service.resend.Emails, "send", _raise)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(_BoomError):
            send_password_reset_email("tim@catchtrust.org", RESET_LINK, "Tim")

    assert RESET_LINK not in caplog.text
    assert "SUPER-SECRET-RESET-TOKEN" not in caplog.text
    assert "Failed to send" in caplog.text  # the log line itself still fires, just without the link


# ---------------------------------------------------------------------------
# Success path: still no link in logs
# ---------------------------------------------------------------------------

def test_send_password_reset_email_succeeds_when_resend_configured_and_ok(monkeypatch, caplog):
    monkeypatch.setattr(Config, "RESEND_API_KEY", "fake-key-for-test")
    monkeypatch.setattr(email_service.resend.Emails, "send", lambda payload: {"id": "fake-id"})

    with caplog.at_level(logging.DEBUG):
        send_password_reset_email("tim@catchtrust.org", RESET_LINK, "Tim")  # must not raise

    assert RESET_LINK not in caplog.text
    assert "SUPER-SECRET-RESET-TOKEN" not in caplog.text


# ---------------------------------------------------------------------------
# Brand presentation: lowercase wordmark, no <img> anywhere (Gmail blocks
# images by default; a broken icon on a password reset email reads as
# phishing -- see the module docstring's constraints).
# ---------------------------------------------------------------------------

def _capture_sent_html(monkeypatch, send_fn, *args):
    """Run one send_*_email call with Resend mocked, returning the html
    payload that would have been sent -- without touching the network."""
    monkeypatch.setattr(Config, "RESEND_API_KEY", "fake-key-for-test")
    captured = {}

    def _fake_send(payload):
        captured["html"] = payload["html"]
        return {"id": "fake-id"}

    monkeypatch.setattr(email_service.resend.Emails, "send", _fake_send)
    send_fn(*args)
    return captured["html"]


@pytest.mark.parametrize(
    "send_fn, args",
    [
        (send_invite_email, ("tim@catchtrust.org", INVITE_LINK, "CATCH Trust", "Ricki", "location_admin")),
        (send_password_reset_email, ("tim@catchtrust.org", RESET_LINK, "Tim")),
        (send_welcome_email, ("tim@catchtrust.org", "Tim", "CATCH Trust", LOGIN_URL)),
    ],
    ids=["invite", "password_reset", "welcome"],
)
def test_wordmark_renders_lowercase_and_no_img_tag(monkeypatch, send_fn, args):
    html = _capture_sent_html(monkeypatch, send_fn, *args)

    assert '>teko<' in html, "wordmark must render as lowercase 'teko'"
    assert '>Teko<' not in html, "wordmark must never render capitalised"
    assert '<img' not in html.lower(), "no <img> tag allowed -- images are blocked by default and a broken icon reads as phishing"
