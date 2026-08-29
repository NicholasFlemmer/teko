"""Tests for the CwB onboarding blocker: normalize_sa_phone() has a hard
South-African-only allowlist and every outbound WhatsApp send path called it
before sending, so any non-SA number (confirmed live with a UAE number) was
silently refused.

Fix: a new normalize_phone_for_sending() in utils/phone.py, international
(E.164 8-15 digit range) rather than SA-only, swapped in at every outbound
call site. normalize_sa_phone() itself is untouched -- still exported and
still used by the SA-specific migration paths (app.py's
/api/admin/normalize-phones and scripts/normalize_phones.py).
normalize_phone_for_matching() (storage/identity resolution) and
ConversationService._phone_key() (conversation history keys) are out of
scope and untouched.

Covers:
  - normalize_phone_for_sending() unit behaviour (SA canonical unchanged,
    SA local form converted, international numbers accepted, out-of-range
    digit counts rejected)
  - normalize_sa_phone() unchanged -- proven via its own existing behaviour
  - all five outbound call sites, individually, accept a non-SA number:
      services/whatsapp_service.py:37  (send_message)
      services/whatsapp_service.py:177 (send_template_message)
      routes/sessions.py:435           (manual send-reminder endpoint)
      services/scheduler_service.py:102 (check_and_send_reminders)
      services/scheduler_service.py:220 (send_end_session_prompts)
  - the refusal log line for an actually-invalid number includes the masked
    number and a reason, not just "Invalid phone number provided"

Pure unit tests: FirebaseService/WhatsAppService/requests are all stubbed
via monkeypatch, so nothing here touches Firestore or the real WhatsApp API.

Usage:
    cd backend
    pytest tests/test_phone_normalization.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

from datetime import datetime, timedelta, timezone  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

import jwt as _jwt  # noqa: E402
import logging  # noqa: E402
import pytest  # noqa: E402
from flask import Flask  # noqa: E402

from config import Config  # noqa: E402
from utils.phone import normalize_sa_phone, normalize_phone_for_sending  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
from services.whatsapp_service import WhatsAppService  # noqa: E402
from services.scheduler_service import SchedulerService  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from routes.sessions import sessions_bp  # noqa: E402


# ---------------------------------------------------------------------------
# 1. normalize_phone_for_sending() -- unit behaviour
# ---------------------------------------------------------------------------

def test_sa_number_stored_canonical_sends_unchanged():
    assert normalize_phone_for_sending('27821234567') == '27821234567'


def test_sa_number_local_form_becomes_canonical():
    assert normalize_phone_for_sending('0821234567') == '27821234567'


def test_uae_number_accepted():
    """The exact number that failed in production."""
    assert normalize_phone_for_sending('971563271027') == '971563271027'


def test_brazilian_number_accepted():
    assert normalize_phone_for_sending('5511987654321') == '5511987654321'


def test_uk_number_accepted():
    assert normalize_phone_for_sending('447700900123') == '447700900123'


def test_six_digit_string_rejected():
    assert normalize_phone_for_sending('123456') == ''


def test_sixteen_digit_string_rejected():
    assert normalize_phone_for_sending('1234567890123456') == ''


def test_empty_string_rejected():
    assert normalize_phone_for_sending('') == ''


def test_none_rejected():
    assert normalize_phone_for_sending(None) == ''


def test_plus_spaces_and_dashes_cleaned_correctly():
    assert normalize_phone_for_sending('+27 82-123 4567') == '27821234567'


def test_eight_digit_boundary_accepted():
    assert normalize_phone_for_sending('12345678') == '12345678'


def test_fifteen_digit_boundary_accepted():
    assert normalize_phone_for_sending('123456789012345') == '123456789012345'


def test_seven_digit_boundary_rejected():
    assert normalize_phone_for_sending('1234567') == ''


# ---------------------------------------------------------------------------
# 2. normalize_sa_phone() -- unchanged, proven via its own existing
#    behaviour (docstring examples + the SA-only rejection this whole
#    incident hinges on).
# ---------------------------------------------------------------------------

def test_normalize_sa_phone_plus_spaces_unchanged():
    assert normalize_sa_phone('+27 82 123 4567') == '27821234567'


def test_normalize_sa_phone_local_leading_zero_unchanged():
    assert normalize_sa_phone('0821234567') == '27821234567'


def test_normalize_sa_phone_already_canonical_unchanged():
    assert normalize_sa_phone('27821234567') == '27821234567'


def test_normalize_sa_phone_dashes_unchanged():
    assert normalize_sa_phone('+27-82-123-4567') == '27821234567'


def test_normalize_sa_phone_still_rejects_uae_number():
    """This is the exact rejection that caused the production incident --
    must still happen for normalize_sa_phone() itself, since it's still
    used by the SA-specific migration paths."""
    assert normalize_sa_phone('971563271027') == ''


def test_normalize_sa_phone_still_rejects_too_short():
    assert normalize_sa_phone('12345') == ''


# ---------------------------------------------------------------------------
# 3a/3b. services/whatsapp_service.py -- send_message and
#        send_template_message, each individually, accept a non-SA number.
# ---------------------------------------------------------------------------

class _FakeResponse:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {'messages': [{'id': 'wamid.OUT1'}]}


def test_send_message_accepts_uae_number(monkeypatch):
    captured = {}

    def _fake_post(url, json=None, headers=None, timeout=None):
        captured['payload'] = json
        return _FakeResponse()

    monkeypatch.setattr('services.whatsapp_service.requests.post', _fake_post)

    result = WhatsAppService.send_message(phone_number='971563271027', message_text='hi')

    assert result['success'] is True
    assert captured['payload']['to'] == '971563271027'


def test_send_template_message_accepts_brazilian_number(monkeypatch):
    captured = {}

    def _fake_post(url, json=None, headers=None, timeout=None):
        captured['payload'] = json
        return _FakeResponse()

    monkeypatch.setattr('services.whatsapp_service.requests.post', _fake_post)

    result = WhatsAppService.send_template_message(
        phone_number='5511987654321', template_name='session_reminder',
    )

    assert result['success'] is True
    assert captured['payload']['to'] == '5511987654321'


def test_send_message_refusal_log_includes_masked_number_and_reason(caplog):
    """A number outside the accepted range must still be refused, and the
    refusal log must be diagnosable: masked number + reason, not just the
    old bare 'Invalid phone number provided'."""
    with caplog.at_level(logging.WARNING):
        result = WhatsAppService.send_message(phone_number='123456', message_text='hi')

    assert result['success'] is False
    assert '****3456' in caplog.text
    assert '8-15 digits' in caplog.text
    assert '123456' not in caplog.text  # the raw number itself must never appear


# ---------------------------------------------------------------------------
# 3c. routes/sessions.py:435 -- the manual send-reminder endpoint, in
#     isolation via a minimal Flask app (same pattern as
#     test_org_id_auth_wiring.py's sessions_client fixture).
# ---------------------------------------------------------------------------

def _make_raw_token(role='super_admin', org_id=None, username='test-user'):
    payload = {
        'username': username,
        'role': role,
        'org_id': org_id,
        'exp': datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return _jwt.encode(payload, Config.SECRET_KEY, algorithm='HS256')


def _auth_header(token):
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def sessions_client(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(sessions_bp, url_prefix='/api/sessions')
    app.testing = True

    session = {
        'id': 'sess-1',
        'org_id': 'org-a',
        'location_id': None,
        'address': 'TBC',
        'start_time': '10:00',
        'coach_ids': ['coach-1'],
    }
    coach = {'id': 'coach-1', 'org_id': 'org-a', 'name': 'Ahmed', 'phone_number': '971563271027'}

    monkeypatch.setattr(FirebaseService, 'get_session', lambda session_id, org_id: dict(session))
    monkeypatch.setattr(FirebaseService, 'get_session_coach_ids', lambda s: list(s['coach_ids']))
    monkeypatch.setattr(FirebaseService, 'get_coach', lambda cid, org_id: dict(coach))
    monkeypatch.setattr(FirebaseService, 'get_location', lambda loc_id, org_id: None)
    monkeypatch.setattr(FirebaseService, 'create_check_in_token', lambda *a, **kw: None)
    monkeypatch.setattr(FirebaseService, 'update_session', lambda *a, **kw: None)

    sent_calls = []

    def _fake_send_check_in_reminder(**kwargs):
        sent_calls.append(kwargs)
        return {'success': True, 'rendered_text': 'reminder sent'}

    monkeypatch.setattr(WhatsAppService, 'send_check_in_reminder', _fake_send_check_in_reminder)

    client = app.test_client()
    client.sent_calls = sent_calls
    return client


def test_send_reminder_endpoint_accepts_uae_coach_number(sessions_client):
    token = _make_raw_token()

    resp = sessions_client.post('/api/sessions/sess-1/send-reminder', headers=_auth_header(token))

    assert resp.status_code == 200
    body = resp.get_json()
    assert body['results'][0]['success'] is True
    assert 'error' not in body['results'][0]
    assert len(sessions_client.sent_calls) == 1
    assert sessions_client.sent_calls[0]['coach_phone'] == '971563271027'


# ---------------------------------------------------------------------------
# 3d. services/scheduler_service.py:102 -- check_and_send_reminders,
#     individually, accepts a non-SA coach number.
# ---------------------------------------------------------------------------

class _FakeSnapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class _FakeDocRef:
    def __init__(self, doc_id, data):
        self._doc_id = doc_id
        self._data = data

    def get(self):
        return _FakeSnapshot(self._doc_id, self._data)

    def update(self, data):
        pass


class _FakeCollection:
    def __init__(self, docs_by_id):
        self._docs_by_id = docs_by_id or {}

    def document(self, doc_id):
        return _FakeDocRef(doc_id, self._docs_by_id.get(doc_id))

    def where(self, *args, **kwargs):
        return self

    def stream(self):
        return iter([])


class _FakeDb:
    def __init__(self, collections):
        self._collections = collections

    def collection(self, name):
        return _FakeCollection(self._collections.get(name, {}))


_JOHANNESBURG = ZoneInfo('Africa/Johannesburg')


def _due_session(session_id='sess-1', org_id='org-a', coach_id='coach-1'):
    # SchedulerService now resolves "now" per-session via FirebaseService.
    # get_org_now(session['org_id']) -- the fake db below gives org-a this
    # same Africa/Johannesburg zone (fixed UTC+2, no DST) so this is
    # equivalent to the old hardcoded SAST constant.
    when = datetime.now(_JOHANNESBURG).replace(tzinfo=None) + timedelta(minutes=Config.REMINDER_MINUTES_BEFORE / 2)
    return {
        'id': session_id,
        'org_id': org_id,
        'status': 'scheduled',
        'date': when.strftime('%Y-%m-%d'),
        'start_time': when.strftime('%H:%M'),
        'location_id': None,
        'coach_id': coach_id,
        'coach_ids': [coach_id],
    }


def test_check_and_send_reminders_accepts_uae_coach_number(monkeypatch):
    session = _due_session()
    coach = {'id': 'coach-1', 'org_id': 'org-a', 'name': 'Ahmed', 'phone_number': '971563271027'}

    fake_db = _FakeDb({
        'coaches': {'coach-1': coach},
        'organisations': {'org-a': {'timezone': 'Africa/Johannesburg'}},
    })
    monkeypatch.setattr(FirebaseService, 'get_db', lambda: fake_db)
    monkeypatch.setattr(FirebaseService, 'get_sessions_for_reminder', lambda target: [dict(session)])
    monkeypatch.setattr(FirebaseService, 'create_check_in_token', lambda *a, **kw: None)
    monkeypatch.setattr(ConversationService, 'save_message', lambda *a, **kw: None)

    sent_calls = []

    def _fake_send_check_in_reminder(**kwargs):
        sent_calls.append(kwargs)
        return {'success': True, 'rendered_text': 'reminder sent'}

    monkeypatch.setattr(WhatsAppService, 'send_check_in_reminder', _fake_send_check_in_reminder)

    SchedulerService.check_and_send_reminders()

    assert len(sent_calls) == 1
    assert sent_calls[0]['coach_phone'] == '971563271027'


# ---------------------------------------------------------------------------
# 3e. services/scheduler_service.py:220 -- send_end_session_prompts,
#     individually, accepts a non-SA coach number.
# ---------------------------------------------------------------------------

class _FakeDoc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return self._data


class _FakeQueryable:
    def __init__(self, docs):
        self._docs = docs

    def where(self, *args, **kwargs):
        return self

    def stream(self):
        return iter(self._docs)


class _FakeSessionsDb:
    def __init__(self, docs):
        self._docs = docs

    def collection(self, name):
        assert name == 'sessions'
        return _FakeQueryable(self._docs)


def test_send_end_session_prompts_accepts_uae_coach_number(monkeypatch):
    coach = {'id': 'coach-1', 'name': 'Ahmed', 'phone_number': '971563271027'}
    # No org_id on this session -> get_org_now(None) falls back to UTC, so
    # build the fixture against that same clock.
    end = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    start = end - timedelta(hours=1)
    session = {
        'id': 'sess-1',
        'status': 'checked_in',
        'date': end.strftime('%Y-%m-%d'),
        'start_time': start.strftime('%H:%M'),
        'end_time': end.strftime('%H:%M'),
        'coach_ids': [coach['id']],
    }

    docs = [_FakeDoc(session['id'], {k: v for k, v in session.items() if k != 'id'})]
    fake_db = _FakeSessionsDb(docs)
    monkeypatch.setattr(FirebaseService, 'get_db', lambda: fake_db)
    monkeypatch.setattr(FirebaseService, 'get_coach', lambda coach_id, org_id: dict(coach))
    monkeypatch.setattr(FirebaseService, 'update_session', lambda *a, **kw: None)
    monkeypatch.setattr(ConversationService, 'save_message', lambda *a, **kw: None)

    sent_calls = []

    def _fake_send_message(phone_number, message_text, check_in_url=None):
        sent_calls.append({'phone_number': phone_number, 'message_text': message_text})
        return {'success': True, 'data': {}, 'status_code': 200}

    monkeypatch.setattr(WhatsAppService, 'send_message', _fake_send_message)

    result = SchedulerService.send_end_session_prompts()

    assert result['prompts_sent'] == 1
    assert len(sent_calls) == 1
    assert sent_calls[0]['phone_number'] == '971563271027'
