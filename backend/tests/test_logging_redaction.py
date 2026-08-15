"""Tests for the logging-redaction work: mask_phone(), the redacted log
lines in app.py/conversation_service.py/whatsapp_service.py, and the
logging configuration added in utils/logging_config.py.

Pure unit tests: FirebaseService/WhatsAppService/requests are stubbed via
monkeypatch, so nothing here touches Firestore or the real WhatsApp API.

Usage:
    cd backend
    FIREBASE_PROJECT_ID=teko-staging-tgh pytest tests/test_logging_redaction.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv  # noqa: E402

STAGING_ENV_PATH = os.path.join(os.path.dirname(__file__), '..', '.env.staging')
if os.path.exists(STAGING_ENV_PATH):
    load_dotenv(dotenv_path=STAGING_ENV_PATH, override=True)
    os.environ['FIREBASE_CREDENTIALS_PATH'] = ''

import io  # noqa: E402
import logging  # noqa: E402

import pytest  # noqa: E402

from utils.phone import mask_phone  # noqa: E402
from utils.logging_config import configure_logging  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from services.whatsapp_service import WhatsAppService  # noqa: E402


# ---------------------------------------------------------------------------
# mask_phone()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('raw,expected', [
    ('+27821234567', '****4567'),
    ('27821234567', '****4567'),
    ('0821234567', '****4567'),
    ('+27 82 123 4567', '****4567'),
    ('27-82-123-4567', '****4567'),
])
def test_mask_phone_keeps_only_last_four_digits(raw, expected):
    assert mask_phone(raw) == expected


@pytest.mark.parametrize('raw', ['123', '12', '1', ''])
def test_mask_phone_short_input_reveals_nothing(raw):
    assert mask_phone(raw) == '****'


@pytest.mark.parametrize('raw', [None, 'abc', '+---', '   '])
def test_mask_phone_malformed_input_does_not_raise(raw):
    assert mask_phone(raw) == '****'


def test_mask_phone_never_returns_the_raw_input():
    raw = '+27821234567'
    result = mask_phone(raw)
    assert result != raw
    assert '821234' not in result


# ---------------------------------------------------------------------------
# Redacted log lines: emit without raising, carry masked/no PII
# ---------------------------------------------------------------------------

RAW_PHONE = '27821234567'
MASKED_PHONE = '****4567'


def test_conversation_service_unregistered_number_logs_masked_phone_not_raw(monkeypatch, caplog):
    monkeypatch.setattr(ConversationService, 'get_coach_by_phone', lambda phone_number: None)
    monkeypatch.setattr(WhatsAppService, 'send_message', lambda **kwargs: {'success': True})

    with caplog.at_level(logging.INFO):
        ConversationService.handle_incoming_message(
            from_number=RAW_PHONE, message_text='hello coach', message_id='wamid.1'
        )

    assert MASKED_PHONE in caplog.text
    assert RAW_PHONE not in caplog.text
    assert 'hello coach' not in caplog.text


def test_conversation_service_location_check_in_logs_masked_phone_no_coordinates(monkeypatch, caplog):
    monkeypatch.setattr(ConversationService, 'get_coach_by_phone', lambda phone_number: None)
    monkeypatch.setattr(WhatsAppService, 'send_message', lambda **kwargs: {'success': True})

    latitude, longitude = -34.04743136, 18.70609173
    with caplog.at_level(logging.INFO):
        ConversationService.handle_location_check_in(
            from_number=RAW_PHONE, latitude=latitude, longitude=longitude, message_id='wamid.2'
        )

    assert MASKED_PHONE in caplog.text
    assert RAW_PHONE not in caplog.text
    assert str(latitude) not in caplog.text
    assert str(longitude) not in caplog.text


def test_whatsapp_service_send_message_logs_masked_phone_not_raw(monkeypatch, caplog):
    class _FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {'messages': [{'id': 'wamid.OUT1'}]}

    monkeypatch.setattr('services.whatsapp_service.requests.post', lambda *a, **kw: _FakeResponse())

    with caplog.at_level(logging.DEBUG):
        result = WhatsAppService.send_message(
            phone_number=RAW_PHONE,
            message_text='Your secret session details are ready',
        )

    assert result['success'] is True
    assert MASKED_PHONE in caplog.text
    assert RAW_PHONE not in caplog.text
    assert 'Your secret session details are ready' not in caplog.text


def test_whatsapp_service_send_message_failure_path_does_not_raise(monkeypatch, caplog):
    """Redacted lines must not raise even on the error path (e.g. malformed
    phone_number reaching mask_phone with no digits at all)."""
    class _FakeErrorResponse:
        status_code = 401
        text = '{"error": "unauthorized"}'

        def json(self):
            return {'error': 'unauthorized'}

    import requests as real_requests

    def _raise(*a, **kw):
        err = real_requests.exceptions.RequestException('boom')
        err.response = _FakeErrorResponse()
        raise err

    monkeypatch.setattr('services.whatsapp_service.requests.post', _raise)

    with caplog.at_level(logging.DEBUG):
        result = WhatsAppService.send_message(phone_number=RAW_PHONE, message_text='hi')

    assert result['success'] is False
    assert RAW_PHONE not in caplog.text


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

def test_configure_logging_defaults_to_info(monkeypatch):
    monkeypatch.delenv('LOG_LEVEL', raising=False)
    level = configure_logging()
    assert level == logging.INFO


def test_configure_logging_respects_log_level_env_var(monkeypatch):
    monkeypatch.setenv('LOG_LEVEL', 'WARNING')
    try:
        level = configure_logging()
        assert level == logging.WARNING
    finally:
        configure_logging()  # restore INFO for any tests that run after


def test_configure_logging_produces_info_output_on_stdout(monkeypatch):
    monkeypatch.delenv('LOG_LEVEL', raising=False)
    configure_logging()

    root_logger = logging.getLogger()
    stream = root_logger.handlers[0].stream if root_logger.handlers else None
    assert stream is not None, "configure_logging() must attach a handler with a stream"

    # Redirect the configured handler's stream to a buffer we can inspect,
    # then confirm an INFO record actually gets formatted and written.
    buffer = io.StringIO()
    original_stream = root_logger.handlers[0].stream
    root_logger.handlers[0].stream = buffer
    try:
        test_logger = logging.getLogger('test_configure_logging_produces_info_output_on_stdout')
        test_logger.info("probe message for stdout capture test")
    finally:
        root_logger.handlers[0].stream = original_stream

    output = buffer.getvalue()
    assert 'probe message for stdout capture test' in output
    assert 'INFO' in output
    assert 'test_configure_logging_produces_info_output_on_stdout' in output


def test_configure_logging_debug_is_suppressed_at_info_level(monkeypatch):
    monkeypatch.delenv('LOG_LEVEL', raising=False)
    configure_logging()

    root_logger = logging.getLogger()
    buffer = io.StringIO()
    original_stream = root_logger.handlers[0].stream
    root_logger.handlers[0].stream = buffer
    try:
        test_logger = logging.getLogger('test_configure_logging_debug_is_suppressed_at_info_level')
        test_logger.debug("this debug line must not appear at INFO level")
    finally:
        root_logger.handlers[0].stream = original_stream

    assert 'this debug line must not appear' not in buffer.getvalue()
