"""Unit tests for safeguarding detection independence from identity
resolution -- specifically the phone-collision path added alongside
PersonService._coach_collisions (see person_service.py).

Safeguarding keyword detection must never depend on knowing who sent a
message. Before this change, ConversationService.handle_incoming_message
ran detect_safeguarding_matches() only AFTER a successful person
resolution -- so a coach caught in a phone collision (resolve() refuses,
per services/person_service.py) got a generic "unrecognised sender" reply
and their message's content was never even scanned for safeguarding
keywords. These tests cover the fix: detection now runs unconditionally,
and a match from a colliding number alerts every colliding org directly
(via PersonService.get_colliding_org_ids), with no message content, no
matched keyword, and no full phone number in that alert -- one org must
never see another org's disclosure.

Four groups, matching the four required behaviours:
  1. A colliding number's safeguarding match alerts every colliding org.
  2. That alert carries no message content / keyword / full number.
  3. A normal (non-colliding) coach's safeguarding match is unaffected.
  4. A genuinely unknown number (no collision) still notifies nobody.

Mocked Resend transport throughout (same convention as
tests/test_safeguarding_alerts.py) -- no real email is ever sent, and
nothing here touches real Firestore.

Usage:
    cd backend
    pytest tests/test_safeguarding_phone_collision.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest  # noqa: E402

from config import Config  # noqa: E402
from services import email_service  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
import services.conversation_service as conversation_service_module  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from services.gemini_service import GeminiService  # noqa: E402
from services.person_service import PersonService  # noqa: E402
from services.whatsapp_service import WhatsAppService  # noqa: E402

STUBBED_AI_REPLY = "This is a stubbed AI reply."
FULL_PHONE = '27821234567'
RAW_MESSAGE = "he hit me at home"


@pytest.fixture
def resend_capture(monkeypatch):
    """Mock the Resend transport itself (not the alert-builder functions)
    so subject/body content is real, rendered output -- never a real send."""
    monkeypatch.setattr(Config, "RESEND_API_KEY", "fake-key-for-test")
    captured = []

    def _fake_send(payload):
        captured.append(payload)
        return {"id": "fake-id"}

    monkeypatch.setattr(email_service.resend.Emails, "send", _fake_send)
    return captured


def _org(org_id, name, lead_email=None):
    org = {'id': org_id, 'name': name, 'type': 'sports'}
    if lead_email is not None:
        org['safeguarding_lead_email'] = lead_email
    return org


def _send_reply_capture(monkeypatch):
    sent = {}

    def _fake_send(phone_number, message_text):
        sent['message_text'] = message_text
        return {'success': True}

    monkeypatch.setattr(WhatsAppService, 'send_message', _fake_send)
    return sent


# ---------------------------------------------------------------------------
# Group 1 & 2: a colliding number's safeguarding match alerts every
# colliding org, with no message content / keyword / full number in it.
# ---------------------------------------------------------------------------

def test_colliding_number_safeguarding_match_alerts_every_colliding_org(monkeypatch, resend_capture):
    monkeypatch.setattr(PersonService, 'resolve', classmethod(lambda cls, phone: None))
    monkeypatch.setattr(PersonService, 'get_colliding_org_ids', classmethod(lambda cls, phone: ['org-a', 'org-b']))
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda oid: {
        'org-a': _org('org-a', 'Org A', 'lead-a@orga.org'),
        'org-b': _org('org-b', 'Org B', 'lead-b@orgb.org'),
    }[oid])

    sent = _send_reply_capture(monkeypatch)

    ConversationService.handle_incoming_message(FULL_PHONE, RAW_MESSAGE, 'msg-1')

    recipients = sorted(call['to'][0] for call in resend_capture)
    assert recipients == ['lead-a@orga.org', 'lead-b@orgb.org'], (
        "Both colliding orgs' safeguarding leads must be alerted -- neither picked, neither skipped."
    )
    assert all(len(call['to']) == 1 for call in resend_capture), "each org alerted individually, never CC'd together"

    # The colliding coach must be told their number needs attention, NOT
    # that they're unregistered -- they're registered twice.
    assert sent['message_text'] == ConversationService.PHONE_NEEDS_ATTENTION_MESSAGE
    assert 'unregistered' not in sent['message_text'].lower()
    assert "isn't registered" not in sent['message_text']


def test_colliding_number_alert_falls_back_to_location_admins_per_org(monkeypatch, resend_capture):
    """Same as above, but neither org has a safeguarding_lead_email set --
    must fall back to that org's own active location_admins, exactly as
    the existing (non-collision) alert path does."""
    monkeypatch.setattr(PersonService, 'resolve', classmethod(lambda cls, phone: None))
    monkeypatch.setattr(PersonService, 'get_colliding_org_ids', classmethod(lambda cls, phone: ['org-a', 'org-b']))
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda oid: {
        'org-a': _org('org-a', 'Org A'),
        'org-b': _org('org-b', 'Org B'),
    }[oid])
    monkeypatch.setattr(FirebaseService, 'get_all_admins_by_org', lambda oid: {
        'org-a': [{'org_id': 'org-a', 'email': 'admin-a@orga.org', 'role': 'location_admin', 'status': 'active'}],
        'org-b': [{'org_id': 'org-b', 'email': 'admin-b@orgb.org', 'role': 'location_admin', 'status': 'active'}],
    }[oid])

    _send_reply_capture(monkeypatch)

    ConversationService.handle_incoming_message(FULL_PHONE, RAW_MESSAGE, 'msg-1')

    recipients = sorted(call['to'][0] for call in resend_capture)
    assert recipients == ['admin-a@orga.org', 'admin-b@orgb.org']


def test_colliding_number_alert_carries_no_message_content_keyword_or_full_number(monkeypatch, resend_capture):
    monkeypatch.setattr(PersonService, 'resolve', classmethod(lambda cls, phone: None))
    monkeypatch.setattr(PersonService, 'get_colliding_org_ids', classmethod(lambda cls, phone: ['org-a', 'org-b']))
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda oid: {
        'org-a': _org('org-a', 'Org A', 'lead-a@orga.org'),
        'org-b': _org('org-b', 'Org B', 'lead-b@orgb.org'),
    }[oid])

    _send_reply_capture(monkeypatch)

    distinctive_message = "He   HIT me!! 😢 at home... please help"
    ConversationService.handle_incoming_message(FULL_PHONE, distinctive_message, 'msg-1')

    assert len(resend_capture) == 2
    for call in resend_capture:
        haystack = call['subject'] + call['html']
        assert distinctive_message not in haystack, "raw message text must never appear in a collision alert"
        assert 'hit me' not in haystack.lower(), "the matched keyword must never appear in a collision alert"
        assert 'physical_abuse' not in haystack.lower(), "the matched category must never appear in a collision alert"
        assert FULL_PHONE not in haystack, "the full phone number must never appear in a collision alert"
        # Only the last 4 digits are permitted.
        assert FULL_PHONE[-4:] in call['html']
        # One org's alert must never mention the other org's name.
        other_org_name = 'Org B' if 'Org A' in call['html'] else 'Org A'
        assert other_org_name not in call['html'], "one org's alert must never name the other colliding org"


# ---------------------------------------------------------------------------
# Group 3: a normal (non-colliding) coach's safeguarding match is
# unaffected -- same flag recording, same alert dispatch, same reply.
# ---------------------------------------------------------------------------

@pytest.fixture
def drive_normal_coach(monkeypatch):
    """Replicates the coach path far enough for handle_incoming_message
    to run to completion and produce a real AI reply, same stubs as
    tests/test_safeguarding_alerts.py's `drive` fixture."""
    monkeypatch.setattr(ConversationService, 'get_pending_attendance', classmethod(lambda cls, phone: None))
    monkeypatch.setattr(ConversationService, 'clear_pending_attendance', classmethod(lambda cls, phone: None))
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda *a, **kw: [])
    monkeypatch.setattr(FirebaseService, 'get_all_teams', lambda org_id: [])
    monkeypatch.setattr(FirebaseService, 'get_all_content', lambda org_id: [])
    monkeypatch.setattr(FirebaseService, 'get_all_urls', lambda org_id: [])
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda oid: {'id': oid, 'type': 'sports'})
    monkeypatch.setattr(ConversationService, 'get_conversation_history', classmethod(lambda cls, phone, limit=10: []))
    monkeypatch.setattr(ConversationService, 'save_message', classmethod(lambda cls, phone, role, content: None))
    monkeypatch.setattr(GeminiService, 'generate_custom_message', lambda prompt: STUBBED_AI_REPLY)

    coach = {
        'id': 'coach-1',
        'org_id': 'org-a',
        'name': 'Alice',
        'phone_number': FULL_PHONE,
        'person_type': 'coach',
    }
    monkeypatch.setattr(PersonService, 'resolve', classmethod(lambda cls, phone: coach))

    def _get_colliding_should_not_be_called(cls, phone):
        raise AssertionError(
            "get_colliding_org_ids must not be consulted when resolve() already returned a person"
        )
    monkeypatch.setattr(PersonService, 'get_colliding_org_ids', classmethod(_get_colliding_should_not_be_called))

    return _send_reply_capture(monkeypatch)


def test_normal_coach_safeguarding_match_behaves_exactly_as_before(monkeypatch, drive_normal_coach):
    recorded = {}

    def _fake_record_flag(**kwargs):
        recorded.update(kwargs)
        return {'id': 'flag-1', **kwargs}

    monkeypatch.setattr(conversation_service_module, 'record_safeguarding_flag', _fake_record_flag)

    alerted = {}

    def _fake_dispatch(flag):
        alerted['flag'] = flag

    monkeypatch.setattr(conversation_service_module, 'send_safeguarding_alert', _fake_dispatch)

    ConversationService.handle_incoming_message(FULL_PHONE, RAW_MESSAGE, 'msg-1')

    assert recorded['org_id'] == 'org-a'
    assert recorded['person_id'] == 'coach-1'
    assert recorded['person_type'] == 'coach'
    assert recorded['person_name'] == 'Alice'
    assert recorded['message_text'] == RAW_MESSAGE
    assert alerted['flag']['id'] == 'flag-1', "send_safeguarding_alert must still be dispatched with the recorded flag"
    assert drive_normal_coach['message_text'] == STUBBED_AI_REPLY, "the coach's normal reply must be completely unaffected"


def test_normal_coach_no_keyword_records_no_flag(monkeypatch, drive_normal_coach):
    """Regression guard alongside the above: a normal coach message with
    no safeguarding keyword must still record nothing, same as before."""
    def _fail_if_called(**kwargs):
        raise AssertionError("record_safeguarding_flag must not be called when there is no keyword match")
    monkeypatch.setattr(conversation_service_module, 'record_safeguarding_flag', _fail_if_called)

    ConversationService.handle_incoming_message(FULL_PHONE, "what time is training tomorrow", 'msg-2')

    assert drive_normal_coach['message_text'] == STUBBED_AI_REPLY


# ---------------------------------------------------------------------------
# Group 4: a genuinely unknown number (no collision) still notifies
# nobody -- behaviour here is intentionally unchanged.
# ---------------------------------------------------------------------------

def test_unknown_number_with_no_collision_notifies_nobody(monkeypatch, resend_capture):
    monkeypatch.setattr(PersonService, 'resolve', classmethod(lambda cls, phone: None))
    monkeypatch.setattr(PersonService, 'get_colliding_org_ids', classmethod(lambda cls, phone: []))

    def _org_lookup_should_not_be_called(oid):
        raise AssertionError("no org lookup should happen for a phone with no known collision")
    monkeypatch.setattr(FirebaseService, 'get_organisation', _org_lookup_should_not_be_called)

    def _collision_alert_should_not_be_called(colliding_org_ids, phone_number):
        raise AssertionError("send_phone_collision_alert must not be called when there is no colliding org")
    monkeypatch.setattr(conversation_service_module, 'send_phone_collision_alert', _collision_alert_should_not_be_called)

    sent = _send_reply_capture(monkeypatch)

    ConversationService.handle_incoming_message(FULL_PHONE, RAW_MESSAGE, 'msg-1')

    assert resend_capture == [], "nobody should be emailed for a genuinely unknown number"
    assert sent['message_text'] == ConversationService.UNRECOGNISED_SENDER_MESSAGE, (
        "an unrecognised number with no collision must get the original, unchanged reply"
    )
