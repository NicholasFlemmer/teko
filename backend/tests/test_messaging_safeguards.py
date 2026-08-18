"""Tests for the messaging safeguards added after the mark_missed_sessions
correction incident: 27 sessions corrected to 'checked_in' caused
send_end_session_prompts to message 17 real coaches (135 messages total,
one coach got 21) about sessions dating back to April -- because the job
had no upper bound on how stale a "just finished" session could be.

Covers:
  - the END_PROMPT_MAX_AGE_HOURS age guard on send_end_session_prompts
  - WHATSAPP_SENDING_ENABLED kill switch on WhatsAppService
  - scheduled sends being recorded via ConversationService.save_message
  - a direct simulation of the incident itself

Pure unit tests: FirebaseService/WhatsAppService/ConversationService/
requests are all stubbed via monkeypatch, so nothing here touches
Firestore or the real WhatsApp API.

Usage:
    cd backend
    FIREBASE_PROJECT_ID=teko-staging-tgh pytest tests/test_messaging_safeguards.py -v
"""
import sys
import os
import importlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv  # noqa: E402

STAGING_ENV_PATH = os.path.join(os.path.dirname(__file__), '..', '.env.staging')
if os.path.exists(STAGING_ENV_PATH):
    load_dotenv(dotenv_path=STAGING_ENV_PATH, override=True)
    os.environ['FIREBASE_CREDENTIALS_PATH'] = ''

from datetime import datetime, timedelta  # noqa: E402

import pytest  # noqa: E402

from config import Config  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
from services.scheduler_service import SchedulerService, SAST  # noqa: E402
from services.whatsapp_service import WhatsAppService  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes for the sessions collection query used by send_end_session_prompts
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


class _FakeDb:
    def __init__(self, docs):
        self._docs = docs

    def collection(self, name):
        assert name == 'sessions'
        return _FakeQueryable(self._docs)


COACH = {'id': 'coach-1', 'name': 'Test Coach', 'phone_number': '+27821234567'}


def _install_fakes(monkeypatch, sessions, coach=COACH):
    """sessions: list of dicts (each must include 'id'). Wires up
    get_db/get_coach/update_session/WhatsAppService.send_message/
    ConversationService.save_message and returns dicts capturing calls."""
    docs = [_FakeDoc(s['id'], {k: v for k, v in s.items() if k != 'id'}) for s in sessions]
    fake_db = _FakeDb(docs)
    monkeypatch.setattr(FirebaseService, 'get_db', lambda: fake_db)
    monkeypatch.setattr(FirebaseService, 'get_coach', lambda coach_id, org_id: dict(coach) if coach else None)

    updates = []
    monkeypatch.setattr(FirebaseService, 'update_session',
                         lambda session_id, data: updates.append((session_id, data)))

    sends = []

    def fake_send_message(phone_number, message_text, check_in_url=None):
        sends.append({'phone_number': phone_number, 'message_text': message_text})
        return {'success': True, 'data': {}, 'status_code': 200}

    monkeypatch.setattr(WhatsAppService, 'send_message', fake_send_message)

    saved_messages = []
    monkeypatch.setattr(ConversationService, 'save_message',
                         lambda coach_phone, role, content: saved_messages.append((coach_phone, role, content)))

    return {'updates': updates, 'sends': sends, 'saved_messages': saved_messages}


def _session_with_end_hours_ago(session_id, hours_ago, status='checked_in', **extra):
    end = datetime.now(SAST).replace(tzinfo=None) - timedelta(hours=hours_ago)
    start = end - timedelta(hours=1)
    session = {
        'id': session_id,
        'status': status,
        'date': end.strftime('%Y-%m-%d'),
        'start_time': start.strftime('%H:%M'),
        'end_time': end.strftime('%H:%M'),
        'coach_ids': [COACH['id']],
    }
    session.update(extra)
    return session


# ---------------------------------------------------------------------------
# Part 1: END_PROMPT_MAX_AGE_HOURS age guard
# ---------------------------------------------------------------------------

def test_session_ended_20_hours_ago_is_skipped_and_end_prompt_sent_not_set(monkeypatch):
    session = _session_with_end_hours_ago('sess-stale', hours_ago=20)
    fakes = _install_fakes(monkeypatch, [session])

    result = SchedulerService.send_end_session_prompts()

    assert fakes['sends'] == []
    assert fakes['updates'] == []
    assert result['prompts_sent'] == 0
    assert result['stale_skipped'] == 1


def test_session_ended_1_hour_ago_is_sent_normally(monkeypatch):
    session = _session_with_end_hours_ago('sess-fresh', hours_ago=1)
    fakes = _install_fakes(monkeypatch, [session])

    result = SchedulerService.send_end_session_prompts()

    assert len(fakes['sends']) == 1
    assert fakes['sends'][0]['phone_number'] == '27821234567'
    assert fakes['updates'] == [('sess-fresh', {'end_prompt_sent': True})]
    assert result['prompts_sent'] == 1
    assert result['stale_skipped'] == 0


def test_cutoff_respects_end_prompt_max_age_hours_env_var(monkeypatch):
    # With a 1-hour cutoff, a session that ended 2 hours ago must be skipped.
    monkeypatch.setattr(Config, 'END_PROMPT_MAX_AGE_HOURS', 1)
    session = _session_with_end_hours_ago('sess-2h', hours_ago=2)
    fakes = _install_fakes(monkeypatch, [session])

    result = SchedulerService.send_end_session_prompts()

    assert fakes['sends'] == []
    assert result['stale_skipped'] == 1


def test_cutoff_widened_lets_an_older_session_through(monkeypatch):
    # With a 48-hour cutoff, a session that ended 20 hours ago must NOT be skipped.
    monkeypatch.setattr(Config, 'END_PROMPT_MAX_AGE_HOURS', 48)
    session = _session_with_end_hours_ago('sess-20h', hours_ago=20)
    fakes = _install_fakes(monkeypatch, [session])

    result = SchedulerService.send_end_session_prompts()

    assert len(fakes['sends']) == 1
    assert result['stale_skipped'] == 0


# ---------------------------------------------------------------------------
# Part 3: WHATSAPP_SENDING_ENABLED kill switch
# ---------------------------------------------------------------------------

def test_sending_disabled_means_no_api_call_and_no_crash(monkeypatch):
    monkeypatch.setattr(Config, 'WHATSAPP_SENDING_ENABLED', False)

    def _boom(*args, **kwargs):
        raise AssertionError("requests.post must not be called when sending is disabled")

    monkeypatch.setattr('services.whatsapp_service.requests.post', _boom)

    result = WhatsAppService.send_message(phone_number='+27821234567', message_text='hello')

    assert result['success'] is False
    assert result['sending_disabled'] is True


def test_sending_disabled_applies_to_template_messages_too(monkeypatch):
    monkeypatch.setattr(Config, 'WHATSAPP_SENDING_ENABLED', False)
    monkeypatch.setattr('services.whatsapp_service.requests.post',
                         lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not call API")))

    result = WhatsAppService.send_template_message(
        phone_number='+27821234567', template_name='session_reminder',
    )

    assert result['success'] is False
    assert result['sending_disabled'] is True


def test_sending_disabled_applies_to_mark_as_read_and_typing_indicator(monkeypatch):
    monkeypatch.setattr(Config, 'WHATSAPP_SENDING_ENABLED', False)
    monkeypatch.setattr('services.whatsapp_service.requests.post',
                         lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not call API")))

    r1 = WhatsAppService.mark_as_read('wamid.1')
    r2 = WhatsAppService.send_typing_indicator('wamid.1')

    assert r1 == {'success': False, 'error': 'WhatsApp sending is disabled', 'sending_disabled': True}
    assert r2 == {'success': False, 'error': 'WhatsApp sending is disabled', 'sending_disabled': True}


def test_sending_enabled_by_default_when_env_var_absent(monkeypatch):
    monkeypatch.delenv('WHATSAPP_SENDING_ENABLED', raising=False)
    import config as config_module
    importlib.reload(config_module)
    try:
        assert config_module.Config.WHATSAPP_SENDING_ENABLED is True
    finally:
        importlib.reload(config_module)


def test_disabled_switch_means_send_end_session_prompts_sends_nothing_and_does_not_lose_the_session(monkeypatch):
    """The caller-side check: when sending is globally disabled, every send
    fails, so end_prompt_sent must NOT be set -- otherwise the session is
    silently lost forever once sending is re-enabled."""
    monkeypatch.setattr(Config, 'WHATSAPP_SENDING_ENABLED', False)
    session = _session_with_end_hours_ago('sess-disabled', hours_ago=1)

    docs = [_FakeDoc(session['id'], {k: v for k, v in session.items() if k != 'id'})]
    fake_db = _FakeDb(docs)
    monkeypatch.setattr(FirebaseService, 'get_db', lambda: fake_db)
    monkeypatch.setattr(FirebaseService, 'get_coach', lambda coach_id, org_id: dict(COACH))
    updates = []
    monkeypatch.setattr(FirebaseService, 'update_session',
                         lambda session_id, data: updates.append((session_id, data)))
    # Do NOT stub WhatsAppService.send_message here -- let the real disabled
    # path run, proving the guard fires all the way through.
    monkeypatch.setattr('services.whatsapp_service.requests.post',
                         lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not call API")))

    result = SchedulerService.send_end_session_prompts()

    assert result['prompts_sent'] == 0
    assert updates == []  # end_prompt_sent never set -- session isn't lost


# ---------------------------------------------------------------------------
# Part 4: scheduled sends are recorded
# ---------------------------------------------------------------------------

def test_end_session_prompt_send_is_recorded_via_save_message(monkeypatch):
    session = _session_with_end_hours_ago('sess-record', hours_ago=1)
    fakes = _install_fakes(monkeypatch, [session])

    SchedulerService.send_end_session_prompts()

    assert len(fakes['saved_messages']) == 1
    phone, role, content = fakes['saved_messages'][0]
    assert phone == '27821234567'
    assert role == 'assistant'
    assert 'Has your session ended?' in content


# ---------------------------------------------------------------------------
# Simulate the actual incident: 27 sessions corrected to checked_in with
# end times months in the past -- assert zero messages sent.
# ---------------------------------------------------------------------------

def test_incident_simulation_27_ancient_checked_in_sessions_send_zero_messages(monkeypatch):
    sessions = [
        _session_with_end_hours_ago(f'sess-incident-{i}', hours_ago=24 * 30 * ((i % 4) + 1))
        for i in range(27)
    ]
    fakes = _install_fakes(monkeypatch, sessions)

    result = SchedulerService.send_end_session_prompts()

    assert fakes['sends'] == []
    assert fakes['updates'] == []
    assert fakes['saved_messages'] == []
    assert result['prompts_sent'] == 0
    assert result['stale_skipped'] == 27
