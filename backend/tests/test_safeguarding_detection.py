"""Unit tests for safeguarding keyword detection on inbound WhatsApp
messages (services/safeguarding_service.py, services/safeguarding_keywords.py,
and the detection hook in ConversationService.handle_incoming_message).

DETECTION AND RECORDING ONLY: this feature must never send an email,
never alter the reply a coach/participant receives, and never change
conversation flow. Nothing in this test file exercises alerting -- that's
a separate, later step, gated behind the alert_sent field this module
only ever writes as False.

Three groups of tests:
  1. Pure detect_safeguarding_matches() tests -- no I/O, no mocking.
  2. record_safeguarding_flag() tests -- Firestore stubbed via a fake
     collection/doc, same convention as test_token_org_id_scoping.py.
  3. Integration tests through the real handle_incoming_message entry
     point -- everything stubbed, same convention as
     test_command_permissions.py -- proving the hook covers both coach
     and participant messages, never scans the AI's outbound reply, and
     can never break message delivery even when it throws.

IMPORTANT -- read before treating any test here as a regression:
Two of the three required benign-message tests below are marked
`xfail(strict=True)`, not asserted as passing. "coach hit me a great
throwdown today" and "my bruise from batting is sore" are real,
literal false positives against the client's own starter keyword list
("hit me", "my bruise") under correct word-boundary matching -- the
words really do appear in that sequence. The brief explicitly forbids
adding confidence/suppression logic to make these NOT fire ("Do not add
any confidence threshold or suppression logic... every match is
recorded"), so this is not something the implementation can fix without
violating that constraint. xfail pins this as a known, reported
limitation of the CURRENT keyword list -- not something silently
swallowed, and not a test quietly rewritten to pass. See the module
docstring in safeguarding_service.py for the same note.

Usage:
    cd backend
    pytest tests/test_safeguarding_detection.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) now lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

import pytest  # noqa: E402

import services.conversation_service as conversation_service_module  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
from services.gemini_service import GeminiService  # noqa: E402
from services.person_service import PersonService  # noqa: E402
from services.safeguarding_keywords import SAFEGUARDING_KEYWORDS  # noqa: E402
from services.safeguarding_service import (  # noqa: E402
    detect_safeguarding_matches,
    record_safeguarding_flag,
)
from services.whatsapp_service import WhatsAppService  # noqa: E402

STUBBED_AI_REPLY = "This is a stubbed AI reply."


# ---------------------------------------------------------------------------
# Group 1: detect_safeguarding_matches() -- pure, no I/O.
# ---------------------------------------------------------------------------

def test_every_category_is_represented_in_the_keyword_list():
    """Structural guard: the five categories from the brief, no more, no
    fewer, each with at least one term -- catches a typo'd category name
    before it silently produces zero matches for that whole category."""
    assert set(SAFEGUARDING_KEYWORDS.keys()) == {
        'neglect', 'physical_abuse', 'sexual_abuse', 'grooming', 'emotional_abuse',
    }
    for category, terms in SAFEGUARDING_KEYWORDS.items():
        assert terms, f"{category} has no keyword terms"


@pytest.mark.parametrize('category,phrase,expected_term', [
    ('physical_abuse', "He hit me after training.", 'hit me'),
    ('sexual_abuse', "He touched me in the changing room.", 'touched me'),
    ('grooming', "Please, our secret, okay?", 'our secret'),
    ('neglect', "There is no food at home tonight.", 'no food at home'),
    ('emotional_abuse', "I am scared to go home today.", 'scared to go home'),
])
def test_each_category_fires_on_a_representative_phrase(category, phrase, expected_term):
    matches = detect_safeguarding_matches(phrase)
    assert category in matches, f"{category} did not fire on {phrase!r}: matches={matches}"
    assert expected_term in matches[category]


def test_multi_category_message_records_all_matched_categories():
    """A message that legitimately touches more than one category must
    surface every one of them -- the brief is explicit: never pick one."""
    text = "He hit me and told me our secret, don't tell your mom, there's no food at home either."
    matches = detect_safeguarding_matches(text)

    assert 'physical_abuse' in matches
    assert 'grooming' in matches
    assert 'neglect' in matches
    assert 'hit me' in matches['physical_abuse']
    assert 'our secret' in matches['grooming']
    assert "don't tell your mom" in matches['grooming']
    assert 'no food at home' in matches['neglect']


# ---------------------------------------------------------------------------
# Word boundary correctness -- NOT naive substring matching.
# ---------------------------------------------------------------------------

def test_hit_me_fires_as_whole_words():
    matches = detect_safeguarding_matches("please stop, you hit me")
    assert 'physical_abuse' in matches
    assert 'hit me' in matches['physical_abuse']


def test_a_word_merely_containing_the_letters_does_not_fire():
    """The classic word-boundary ("Scunthorpe") case: "draped" contains
    "raped" as a literal substring but is not the word "raped" -- naive
    substring matching would false-positive here, word-boundary regex
    must not."""
    matches = detect_safeguarding_matches("the flag was draped over the stage")
    assert 'sexual_abuse' not in matches
    assert not matches, f"expected no matches at all, got {matches}"


def test_raped_as_a_real_standalone_word_does_fire():
    """The positive control for the test above -- "raped" as its own word
    must still fire; only the substring-inside-another-word case is
    excluded."""
    matches = detect_safeguarding_matches("he raped me")
    assert 'sexual_abuse' in matches
    assert 'raped' in matches['sexual_abuse']


def test_two_word_phrase_does_not_fire_when_run_together_with_no_boundary():
    """"hitme" (no space, e.g. a typo/username-like token) must not match
    the two-word phrase "hit me" -- there is no word boundary between
    "hit" and "me" inside a single contiguous token."""
    matches = detect_safeguarding_matches("my dog is called hitmeharder99")
    assert not matches, f"expected no matches, got {matches}"


# ---------------------------------------------------------------------------
# Case and punctuation variations.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('text', [
    "HE HIT ME YESTERDAY",
    "he Hit Me yesterday",
    "he hit me!",
    "he hit me.",
    "he hit me,",
    "he hit me?",
    "(he hit me)",
    "\"he hit me\"",
    "he   hit   me",  # irregular whitespace between words
])
def test_case_and_punctuation_variations_fire(text):
    matches = detect_safeguarding_matches(text)
    assert 'physical_abuse' in matches, f"expected a match for {text!r}, got {matches}"
    assert 'hit me' in matches['physical_abuse']


# ---------------------------------------------------------------------------
# Benign cricket messages must NOT fire -- see module docstring above for
# why two of these three are marked xfail(strict=True) rather than
# asserted as passing, and why that is not the same thing as "adjusting
# the test to pass."
# ---------------------------------------------------------------------------

def test_benign_cricket_message_beat_them_by_20_runs_does_not_fire():
    """The one genuine true negative of the three required benign cases:
    "beat them" is not "beat me"/"beats me" -- the phrase requires "beat"
    to be immediately followed by "me", which it isn't here."""
    matches = detect_safeguarding_matches("we beat them by 20 runs")
    assert not matches, f"expected no matches, got {matches}"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "KNOWN FALSE POSITIVE, reported not suppressed: 'hit me' appears "
        "literally, as consecutive whole words, in this genuinely benign "
        "cricket sentence ('...hit me a great throwdown...'). The brief "
        "forbids confidence/suppression logic to prevent this, so it "
        "currently fires on physical_abuse. Flagged to the client as a "
        "keyword-list precision issue, not fixed here."
    ),
)
def test_benign_cricket_message_hit_me_a_great_throwdown_does_not_fire():
    matches = detect_safeguarding_matches("coach hit me a great throwdown today")
    assert not matches, f"expected no matches, got {matches}"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "KNOWN FALSE POSITIVE, reported not suppressed: 'my bruise' "
        "appears literally, as consecutive whole words, in this genuinely "
        "benign cricket sentence. Same reasoning as the 'hit me' xfail "
        "above -- the brief forbids suppression logic that would prevent "
        "this from firing."
    ),
)
def test_benign_cricket_message_my_bruise_from_batting_does_not_fire():
    matches = detect_safeguarding_matches("my bruise from batting is sore")
    assert not matches, f"expected no matches, got {matches}"


# ---------------------------------------------------------------------------
# Group 2: record_safeguarding_flag() -- Firestore stubbed.
# ---------------------------------------------------------------------------

class _FakeDocRef:
    def __init__(self, captured):
        self._captured = captured

    def set(self, data):
        self._captured['data'] = data


class _FakeCollection:
    def __init__(self, captured, expected_name):
        self._captured = captured
        self._expected_name = expected_name

    def document(self):
        assert True  # auto-id document, matches create_organisation/auth_token style
        return _FakeDocRef(self._captured)


def _fake_db_for_safeguarding_flags(captured):
    class _FakeDb:
        def collection(self, name):
            assert name == 'safeguarding_flags', f"expected 'safeguarding_flags', got {name!r}"
            return _FakeCollection(captured, 'safeguarding_flags')
    return _FakeDb()


@pytest.fixture
def captured_write(monkeypatch):
    captured = {}
    monkeypatch.setattr(FirebaseService, 'get_db', lambda: _fake_db_for_safeguarding_flags(captured))
    return captured


def test_flag_document_contains_org_id_matching_the_sender(captured_write):
    record_safeguarding_flag(
        org_id='org-a',
        person_id='participant-1',
        person_type='participant',
        person_name='Alex',
        phone_number='27821234567',
        message_text='he hit me',
        message_id='msg-1',
        matches={'physical_abuse': ['hit me']},
    )

    assert captured_write['data']['org_id'] == 'org-a'


def test_message_text_stored_byte_for_byte_identical(captured_write):
    raw_text = "He   HIT me!! 😢 don't tell anyone... \n\tplease"
    record_safeguarding_flag(
        org_id='org-a',
        person_id='participant-1',
        person_type='participant',
        person_name='Alex',
        phone_number='27821234567',
        message_text=raw_text,
        message_id='msg-1',
        matches={'physical_abuse': ['hit me'], 'grooming': ['don\'t tell anyone']},
    )

    assert captured_write['data']['message_text'] == raw_text


def test_all_matched_categories_are_recorded_not_just_one(captured_write):
    record_safeguarding_flag(
        org_id='org-a',
        person_id='participant-1',
        person_type='participant',
        person_name='Alex',
        phone_number='27821234567',
        message_text='he hit me and told me our secret',
        message_id='msg-1',
        matches={'physical_abuse': ['hit me'], 'grooming': ['our secret']},
    )

    stored = captured_write['data']
    assert set(stored['matched_category']) == {'physical_abuse', 'grooming'}
    assert set(stored['matched_terms']) == {'hit me', 'our secret'}


def test_phone_number_is_stored_masked(captured_write):
    record_safeguarding_flag(
        org_id='org-a',
        person_id='participant-1',
        person_type='participant',
        person_name='Alex',
        phone_number='+27821234567',
        message_text='he hit me',
        message_id='msg-1',
        matches={'physical_abuse': ['hit me']},
    )

    stored_phone = captured_write['data']['phone_number']
    assert stored_phone == '****4567'
    assert '27821234567' not in stored_phone


def test_status_and_alert_sent_defaults(captured_write):
    record_safeguarding_flag(
        org_id='org-a',
        person_id='participant-1',
        person_type='participant',
        person_name='Alex',
        phone_number='27821234567',
        message_text='he hit me',
        message_id='msg-1',
        matches={'physical_abuse': ['hit me']},
    )

    stored = captured_write['data']
    assert stored['status'] == 'new'
    assert stored['alert_sent'] is False


def test_record_flag_refuses_to_write_without_org_id(captured_write):
    """Never write an unscoped safeguarding_flags document -- the
    check_in_tokens mistake this collection must not repeat."""
    with pytest.raises(ValueError):
        record_safeguarding_flag(
            org_id=None,
            person_id='participant-1',
            person_type='participant',
            person_name='Alex',
            phone_number='27821234567',
            message_text='he hit me',
            message_id='msg-1',
            matches={'physical_abuse': ['hit me']},
        )

    assert 'data' not in captured_write, "no write should have been attempted without org_id"


# ---------------------------------------------------------------------------
# Group 3: integration through the real handle_incoming_message entry
# point. Same convention as tests/test_command_permissions.py -- every
# underlying data call stubbed, driven through the real production path.
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

    flag_calls = []
    monkeypatch.setattr(
        conversation_service_module, 'record_safeguarding_flag',
        lambda **kwargs: flag_calls.append(kwargs),
    )

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

    _drive.flag_calls = flag_calls
    _drive.monkeypatch = monkeypatch
    return _drive


def test_detection_runs_on_participant_message(drive):
    drive('participant', 'he hit me at home')

    assert len(drive.flag_calls) == 1
    call = drive.flag_calls[0]
    assert call['org_id'] == 'org-a'
    assert call['person_type'] == 'participant'
    assert 'physical_abuse' in call['matches']


@pytest.mark.parametrize('person_type', ['coach', 'participant'])
def test_detection_runs_on_both_person_types(drive, person_type):
    """A coach may relay a concern -- detection must not be participant-only."""
    drive(person_type, 'he hit me at home')

    assert len(drive.flag_calls) == 1
    assert drive.flag_calls[0]['person_type'] == person_type


def test_detection_does_not_run_on_outbound_ai_message(drive):
    """The stubbed AI reply itself contains a keyword phrase -- detection
    must never scan outbound text, only the inbound message. If this
    fired, it would prove the hook is scanning the wrong side of the
    conversation."""
    assert 'stubbed' in STUBBED_AI_REPLY.lower()  # sanity: not a keyword phrase itself
    reply = drive('participant', 'What is a good warm-up drill?')

    assert reply == STUBBED_AI_REPLY
    assert drive.flag_calls == []


def test_no_match_means_no_flag_written(drive):
    drive('participant', 'What time is practice tomorrow?')
    assert drive.flag_calls == []


def test_detection_exception_does_not_prevent_the_reply_being_sent(drive, caplog):
    def _raise(text):
        raise RuntimeError("simulated detection failure")

    drive.monkeypatch.setattr(conversation_service_module, 'detect_safeguarding_matches', _raise)

    with caplog.at_level('ERROR'):
        reply = drive('participant', 'he hit me at home')

    assert reply == STUBBED_AI_REPLY, "the participant must still get their normal reply"


def test_detection_exception_is_logged_at_error(drive, caplog):
    def _raise(text):
        raise RuntimeError("simulated detection failure")

    drive.monkeypatch.setattr(conversation_service_module, 'detect_safeguarding_matches', _raise)

    with caplog.at_level('ERROR'):
        drive('participant', 'he hit me at home', org_id='org-a', message_id='msg-error-test')

    error_records = [r for r in caplog.records if r.levelname == 'ERROR']
    assert any('afeguard' in r.getMessage() for r in error_records), (
        f"expected a safeguarding-related ERROR log, got: {[r.getMessage() for r in error_records]}"
    )
    assert any('msg-error-test' in r.getMessage() for r in error_records), (
        "expected the error log to include the message_id for investigation context"
    )
