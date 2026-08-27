"""Unit tests for safeguarding ALERT emails (services/safeguarding_service.py's
send_safeguarding_alert()/_recipients_for_org(), and
services/email_service.py's send_safeguarding_alert_email()).

This closes the loop started by test_safeguarding_detection.py: a keyword
match, once recorded as a flag, now reaches a human via email.

RECIPIENT RESOLUTION is the highest-stakes part of this feature -- Teko
must never receive a client's safeguarding data, and one org must never
see another org's. Most of the tests below exist to pin that down hard,
including two static/structural guards (source-scan for hardcoded
addresses, and a fake Firestore collection that raises if anything ever
queries the safeguarding_flags collection instead of being handed one
flag directly) rather than relying purely on behavioural coverage.

Five groups:
  1. Recipient resolution (lead email vs. location_admin fallback vs.
     neither), always org-scoped, never Triggr/hardcoded.
  2. Email content (subject neutrality, verbatim body).
  3. alert_sent / sent_at bookkeeping on success and failure.
  4. Integration: a send failure must never affect the participant's
     WhatsApp reply.
  5. Scope guarantee: a pre-existing (pre-feature) unsent flag can never
     be picked up, because nothing here ever queries for one.

Mocked Resend transport throughout (via Config.RESEND_API_KEY +
email_service.resend.Emails.send, same convention as
tests/test_email_service.py) and a stubbed Firestore layer (same
_FakeDocRef/_FakeCollection convention as
tests/test_safeguarding_detection.py). No real email is ever sent, and
nothing here touches real Firestore.

Usage:
    cd backend
    pytest tests/test_safeguarding_alerts.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) now lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

import inspect  # noqa: E402
import logging  # noqa: E402
import re  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

import pytest  # noqa: E402

from config import Config  # noqa: E402
import services.safeguarding_service as safeguarding_service_module  # noqa: E402
from services.safeguarding_service import send_safeguarding_alert  # noqa: E402
from services import email_service  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
import services.conversation_service as conversation_service_module  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from services.gemini_service import GeminiService  # noqa: E402
from services.person_service import PersonService  # noqa: E402
from services.whatsapp_service import WhatsAppService  # noqa: E402

ORG_A = 'org-a'
ORG_B = 'org-b'

STUBBED_AI_REPLY = "This is a stubbed AI reply."

# A message chosen to mirror the irregular-spacing/apostrophe/emoji case
# already exercised in test_safeguarding_detection.py's byte-for-byte
# Firestore test -- deliberately free of HTML metacharacters (<, >, &) so
# the email body's HTML-escaping (quote=False; see email_service.py) is a
# no-op and the byte-for-byte assertions below are meaningful without the
# test itself having to account for escaping.
RAW_MESSAGE = "He   HIT me!! 😢 at home... \n\tplease help"


def _flag(org_id=ORG_A, flag_id='flag-1', **overrides):
    base = {
        'id': flag_id,
        'org_id': org_id,
        'person_id': 'participant-1',
        'person_type': 'participant',
        'person_name': 'Alex Participant',
        'phone_number': '****4567',
        'message_text': RAW_MESSAGE,
        'matched_category': ['physical_abuse'],
        'matched_terms': ['hit me'],
        'message_id': 'msg-1',
        'detected_at': datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc),
        'status': 'new',
        'alert_sent': False,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Fake Firestore for safeguarding_flags -- update() is allowed (that's the
# only write send_safeguarding_alert ever performs, and only on the exact
# document id it was handed); where()/stream() raise, because those are the
# only operations a sweeper/backfill job could use to discover flags on its
# own, and this feature must never do that (see Group 5).
# ---------------------------------------------------------------------------

class _FakeFlagDocRef:
    def __init__(self, captured):
        self._captured = captured

    def update(self, data):
        self._captured['update'] = data


class _FakeFlagsCollection:
    def __init__(self, captured):
        self._captured = captured

    def document(self, doc_id):
        self._captured.setdefault('documents_touched', []).append(doc_id)
        return _FakeFlagDocRef(self._captured)

    def where(self, *a, **kw):
        raise AssertionError(
            "send_safeguarding_alert must never query (.where) the "
            "safeguarding_flags collection -- that would let it discover "
            "pre-existing flags instead of only ever acting on the one "
            "it was directly handed."
        )

    def stream(self, *a, **kw):
        raise AssertionError(
            "send_safeguarding_alert must never .stream() the "
            "safeguarding_flags collection -- same reasoning as where()."
        )


def _fake_db(captured):
    class _FakeDb:
        def collection(self, name):
            assert name == 'safeguarding_flags', f"expected 'safeguarding_flags', got {name!r}"
            return _FakeFlagsCollection(captured)
    return _FakeDb()


@pytest.fixture
def firestore_write(monkeypatch):
    captured = {}
    monkeypatch.setattr(FirebaseService, 'get_db', lambda: _fake_db(captured))
    return captured


@pytest.fixture
def resend_capture(monkeypatch):
    """Mock the Resend transport itself (not send_safeguarding_alert_email)
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


def _admin(org_id, email, role='location_admin', status='active'):
    return {'org_id': org_id, 'email': email, 'role': role, 'status': status}


# ---------------------------------------------------------------------------
# Group 1: recipient resolution.
# ---------------------------------------------------------------------------

def test_lead_email_set_sends_to_that_address_only(monkeypatch, firestore_write, resend_capture):
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda oid: _org(ORG_A, 'Org A', 'lead@orga.org'))

    def _admins_should_not_be_queried(org_id):
        raise AssertionError("safeguarding_lead_email is set -- must short-circuit before checking location_admin accounts")
    monkeypatch.setattr(FirebaseService, 'get_all_admins_by_org', _admins_should_not_be_queried)

    send_safeguarding_alert(_flag())

    assert len(resend_capture) == 1
    assert resend_capture[0]['to'] == ['lead@orga.org']


def test_lead_email_absent_sends_to_every_active_location_admin_individually(monkeypatch, firestore_write, resend_capture):
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda oid: _org(ORG_A, 'Org A'))
    monkeypatch.setattr(FirebaseService, 'get_all_admins_by_org', lambda oid: [
        _admin(ORG_A, 'admin1@orga.org'),
        _admin(ORG_A, 'admin2@orga.org'),
        _admin(ORG_A, 'suspended@orga.org', status='suspended'),   # inactive -- excluded
        _admin(ORG_A, 'coach-role@orga.org', role='coach'),        # wrong role -- excluded
    ])

    send_safeguarding_alert(_flag())

    sent_to = sorted(call['to'][0] for call in resend_capture)
    assert sent_to == ['admin1@orga.org', 'admin2@orga.org']
    # individually -- never more than one address per send
    assert all(len(call['to']) == 1 for call in resend_capture)


def test_no_lead_and_no_location_admin_logs_error_and_sends_nothing(monkeypatch, firestore_write, resend_capture, caplog):
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda oid: _org(ORG_A, 'Org A'))
    monkeypatch.setattr(FirebaseService, 'get_all_admins_by_org', lambda oid: [])

    with caplog.at_level(logging.ERROR):
        send_safeguarding_alert(_flag(flag_id='flag-no-recipients'))

    assert resend_capture == [], "nothing should have been sent"
    assert 'update' not in firestore_write, "alert_sent must be left False -- no Firestore write at all"
    error_records = [r for r in caplog.records if r.levelname == 'ERROR']
    assert any('flag-no-recipients' in r.getMessage() for r in error_records)


def test_recipients_never_cross_org_two_org_fixture(monkeypatch, firestore_write, resend_capture):
    """Defence in depth: even if get_all_admins_by_org ever returned
    admins from more than one org (its own Firestore query is supposed to
    prevent this, but this must never depend on that alone), the
    org_id equality check inside _recipients_for_org must still exclude
    every admin that doesn't belong to the flag's own org."""
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda oid: _org(ORG_A, 'Org A'))
    monkeypatch.setattr(FirebaseService, 'get_all_admins_by_org', lambda oid: [
        _admin(ORG_A, 'admin-a@orga.org'),
        _admin(ORG_B, 'admin-b@orgb.org'),   # wrong org -- must never be a recipient
    ])

    send_safeguarding_alert(_flag(org_id=ORG_A))

    sent_to = [call['to'][0] for call in resend_capture]
    assert sent_to == ['admin-a@orga.org']
    assert 'admin-b@orgb.org' not in sent_to


def test_no_triggr_or_hardcoded_address_can_ever_be_a_recipient(monkeypatch, firestore_write, resend_capture):
    """A super_admin is the Triggr platform role (see routes/auth.py) --
    it must never be eligible as a fallback recipient, even when present
    in the same org's admin_users. Also asserts none of the addresses
    this codebase already hardcodes anywhere (the Resend from-address,
    known @heytriggr.com demo addresses) are ever sent to."""
    forbidden = {
        Config.RESEND_FROM_EMAIL,
        'ricki+qa1@heytriggr.com',
        'ricki+coach@heytriggr.com',
        'founders@heytriggr.com',
    }

    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda oid: _org(ORG_A, 'Org A'))
    monkeypatch.setattr(FirebaseService, 'get_all_admins_by_org', lambda oid: [
        _admin(ORG_A, 'genuine-admin@orga.org'),
        _admin(ORG_A, 'platform@heytriggr.com', role='super_admin'),  # Triggr platform role -- excluded
    ])

    send_safeguarding_alert(_flag())

    sent_to = {call['to'][0] for call in resend_capture}
    assert sent_to == {'genuine-admin@orga.org'}
    assert sent_to.isdisjoint(forbidden)
    assert 'platform@heytriggr.com' not in sent_to


def test_no_hardcoded_address_literal_in_recipient_resolution_source():
    """Static guard, independent of any fixture: _recipients_for_org's own
    source must contain no email-address-shaped string literal at all --
    the only way to be certain there is no baked-in fallback address,
    Triggr or otherwise, that a behavioural test could simply fail to
    exercise."""
    source = inspect.getsource(safeguarding_service_module._recipients_for_org)
    match = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', source)
    assert match is None, f"found an email-address-shaped literal in _recipients_for_org: {match}"


# ---------------------------------------------------------------------------
# Group 2: email content.
# ---------------------------------------------------------------------------

def test_subject_contains_no_message_text_no_category_no_person_name(monkeypatch, firestore_write, resend_capture):
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda oid: _org(ORG_A, 'Org A', 'lead@orga.org'))

    send_safeguarding_alert(_flag(
        person_name='Alex Participant',
        message_text=RAW_MESSAGE,
        matched_category=['physical_abuse'],
        matched_terms=['hit me'],
    ))

    subject = resend_capture[0]['subject']
    assert subject == "Safeguarding alert - Org A"
    assert RAW_MESSAGE not in subject
    assert 'physical_abuse' not in subject
    assert 'Alex Participant' not in subject
    assert 'hit me' not in subject


def test_body_contains_message_text_byte_for_byte_identical(monkeypatch, firestore_write, resend_capture):
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda oid: _org(ORG_A, 'Org A', 'lead@orga.org'))

    send_safeguarding_alert(_flag(message_text=RAW_MESSAGE))

    html = resend_capture[0]['html']
    assert RAW_MESSAGE in html


def test_body_contains_all_required_record_fields_and_no_ai_interpretation(monkeypatch, firestore_write, resend_capture):
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda oid: _org(ORG_A, 'Org A', 'lead@orga.org'))

    flag = _flag(
        person_name='Alex Participant',
        person_type='participant',
        phone_number='****4567',
        message_text=RAW_MESSAGE,
        matched_category=['physical_abuse'],
        matched_terms=['hit me'],
        flag_id='flag-content-check',
    )
    send_safeguarding_alert(flag)

    html = resend_capture[0]['html']
    assert 'Alex Participant' in html
    assert 'Participant' in html                     # which they are
    assert '****4567' in html                         # masked phone
    assert RAW_MESSAGE in html                        # verbatim message
    assert 'physical_abuse' in html                   # matched category
    assert 'hit me' in html                            # matched term
    assert '2026-08-27' in html                        # timestamp
    assert 'flag-content-check' in html                 # flag ID
    assert 'automated keyword detection' in html.lower()
    assert 'has not been assessed by a person' in html.lower()
    assert 'false positive' in html.lower()
    # No AI summary, severity rating, or recommended action -- the client's
    # policy requires a bare factual record.
    for banned in ('severity', 'recommend', 'we suggest', 'you should', 'urgent'):
        assert banned not in html.lower()


# ---------------------------------------------------------------------------
# Group 3: alert_sent / sent_at bookkeeping.
# ---------------------------------------------------------------------------

def test_alert_sent_true_and_sent_at_recorded_on_success(monkeypatch, firestore_write, resend_capture):
    from firebase_admin import firestore as _firestore

    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda oid: _org(ORG_A, 'Org A', 'lead@orga.org'))

    send_safeguarding_alert(_flag(flag_id='flag-success'))

    assert firestore_write['documents_touched'] == ['flag-success']
    update = firestore_write['update']
    assert update['alert_sent'] is True
    assert update['sent_at'] is _firestore.SERVER_TIMESTAMP
    assert update['alert_recipients'] == ['lead@orga.org']


def test_send_failure_leaves_alert_sent_false_and_logs_error(monkeypatch, firestore_write, resend_capture, caplog):
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda oid: _org(ORG_A, 'Org A', 'lead@orga.org'))

    def _raise(**kwargs):
        raise RuntimeError("simulated Resend outage")
    monkeypatch.setattr(safeguarding_service_module, 'send_safeguarding_alert_email', _raise)

    with caplog.at_level(logging.ERROR):
        send_safeguarding_alert(_flag(flag_id='flag-send-fails'))

    assert 'update' not in firestore_write, "alert_sent must stay False -- no Firestore write on send failure"
    error_records = [r for r in caplog.records if r.levelname == 'ERROR']
    assert any('flag-send-fails' in r.getMessage() for r in error_records)


# ---------------------------------------------------------------------------
# Group 4: integration -- a send failure must never touch the reply.
# ---------------------------------------------------------------------------

def _person(org_id, person_type):
    return {
        'id': f'{person_type}-1',
        'org_id': org_id,
        'name': 'Alex',
        'phone_number': '27821234567',
        'person_type': person_type,
    }


@pytest.fixture
def drive(monkeypatch):
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

    def _drive(person_type, text, org_id='org-a', message_id='msg-1'):
        person = _person(org_id, person_type)
        monkeypatch.setattr(PersonService, 'resolve', classmethod(lambda cls, phone: person))

        sent = {}

        def _fake_send(phone_number, message_text):
            sent['message_text'] = message_text
            return {'success': True}

        monkeypatch.setattr(WhatsAppService, 'send_message', _fake_send)

        ConversationService.handle_incoming_message(person['phone_number'], text, message_id)
        return sent.get('message_text')

    _drive.monkeypatch = monkeypatch
    return _drive


def test_email_send_failure_does_not_prevent_the_participant_reply(drive):
    """The flag itself records fine (real record_safeguarding_flag path,
    stubbed Firestore write); only the alert send fails. The reply the
    participant actually receives must be completely unaffected."""
    fake_flag = _flag(org_id='org-a', flag_id='flag-integration')

    drive.monkeypatch.setattr(
        conversation_service_module, 'record_safeguarding_flag',
        lambda **kwargs: fake_flag,
    )

    def _raise(flag):
        raise RuntimeError("simulated total alert failure")
    drive.monkeypatch.setattr(conversation_service_module, 'send_safeguarding_alert', _raise)

    reply = drive('participant', 'he hit me at home')

    assert reply == STUBBED_AI_REPLY


def test_email_send_failure_does_not_prevent_the_coach_reply(drive):
    """Same guarantee on the coach path, which dispatches the alert from
    a different call site (after the WhatsApp send in
    handle_incoming_message itself, not inside _handle_participant_message)."""
    fake_flag = _flag(org_id='org-a', flag_id='flag-integration-coach', person_type='coach')

    drive.monkeypatch.setattr(
        conversation_service_module, 'record_safeguarding_flag',
        lambda **kwargs: fake_flag,
    )

    def _raise(flag):
        raise RuntimeError("simulated total alert failure")
    drive.monkeypatch.setattr(conversation_service_module, 'send_safeguarding_alert', _raise)

    reply = drive('coach', 'he hit me at home')

    assert reply == STUBBED_AI_REPLY


# ---------------------------------------------------------------------------
# Group 5: scope guarantee -- a pre-existing (pre-feature) unsent flag can
# never be picked up, because nothing here ever queries for one. The
# _FakeFlagsCollection above already raises on .where()/.stream() for
# EVERY test in this file; this test names the guarantee directly.
# ---------------------------------------------------------------------------

def test_pre_existing_unsent_flag_is_never_picked_up(monkeypatch, firestore_write, resend_capture):
    """send_safeguarding_alert takes the flag to alert on as a plain
    argument -- there is no query anywhere in safeguarding_service.py for
    documents with alert_sent == False. A flag written before this
    feature shipped (alert_sent already False in Firestore, from
    record_safeguarding_flag's existing default) is therefore
    structurally unreachable: nothing ever iterates the collection
    looking for it. The fake Firestore below raises AssertionError on any
    .where()/.stream() call -- the only operations a sweeper/backfill job
    could use -- proving this call performs neither."""
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda oid: _org(ORG_A, 'Org A', 'lead@orga.org'))

    legacy_flag_id = 'legacy-flag-created-before-this-feature-shipped'
    new_flag = _flag(org_id=ORG_A, flag_id='flag-new-only')

    send_safeguarding_alert(new_flag)

    # Only the one flag explicitly passed in was ever touched -- the
    # legacy flag id never appears anywhere, because nothing ever looked
    # for it.
    assert firestore_write['documents_touched'] == ['flag-new-only']
    assert legacy_flag_id not in firestore_write['documents_touched']
