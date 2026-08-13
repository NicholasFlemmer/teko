"""Unit tests for Phase 2 step 4 part B: real per-command gating via
ConversationService.COMMAND_PERMISSIONS, replacing the old blanket
"participants get a polite decline on anything that isn't /help, /reset,
or Q&A" behaviour from step 3.

The matrix that matters most: every command, both person types, both a
sports org and an ngo org, asserting allowed vs declined. Driven through
the real production entry point (handle_incoming_message, which internally
dispatches to _handle_participant_message for a non-coach person) rather
than calling internal routing methods directly, so this exercises the
actual code path a WhatsApp webhook hits.

Pure unit tests: PersonService.resolve, FirebaseService, GeminiService, and
WhatsAppService are all stubbed via monkeypatch, so nothing here touches
real infrastructure — same convention as test_step3c_fixes.py.

Usage:
    cd backend
    pytest tests/test_command_permissions.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv

STAGING_ENV_PATH = os.path.join(os.path.dirname(__file__), '..', '.env.staging')
if os.path.exists(STAGING_ENV_PATH):
    load_dotenv(dotenv_path=STAGING_ENV_PATH, override=True)
    os.environ['FIREBASE_CREDENTIALS_PATH'] = ''

import pytest  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from services.person_service import PersonService  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
from services.gemini_service import GeminiService  # noqa: E402
from services.whatsapp_service import WhatsAppService  # noqa: E402

STUBBED_AI_REPLY = "This is a stubbed AI reply."

DECLINE_MARKER = "not something you're able to do here"


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
    """Drive a single WhatsApp text message through the real
    handle_incoming_message entry point for a given (org_type, person_type)
    combination, with every underlying data call stubbed so any ALLOWED
    handler completes without touching real infrastructure. Returns the
    captured reply text.
    """
    monkeypatch.setattr(ConversationService, 'get_pending_attendance', classmethod(lambda cls, phone: None))
    monkeypatch.setattr(ConversationService, 'clear_pending_attendance', classmethod(lambda cls, phone: None))
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda *a, **kw: [])
    monkeypatch.setattr(FirebaseService, 'get_all_teams', lambda org_id: [])
    monkeypatch.setattr(FirebaseService, 'get_all_content', lambda org_id: [])
    monkeypatch.setattr(FirebaseService, 'get_all_urls', lambda org_id: [])
    monkeypatch.setattr(ConversationService, 'get_conversation_history', classmethod(lambda cls, phone, limit=10: []))
    monkeypatch.setattr(ConversationService, 'save_message', classmethod(lambda cls, phone, role, content: None))
    monkeypatch.setattr(GeminiService, 'generate_custom_message', lambda prompt: STUBBED_AI_REPLY)

    def _drive(org_type, person_type, text):
        org_id = f'org-{org_type}'
        person = _person(org_id, person_type)
        monkeypatch.setattr(PersonService, 'resolve', classmethod(lambda cls, phone: person))
        monkeypatch.setattr(FirebaseService, 'get_organisation', lambda oid: {'id': oid, 'type': org_type})

        sent = {}

        def _fake_send(phone_number, message_text):
            sent['message_text'] = message_text
            return {'success': True}

        monkeypatch.setattr(WhatsAppService, 'send_message', _fake_send)

        ConversationService.handle_incoming_message(person['phone_number'], text, message_id='qa-test')
        return sent.get('message_text')

    return _drive


# ---------------------------------------------------------------------------
# The matrix: every text command x both person types x both org types.
# ---------------------------------------------------------------------------

TEXT_COMMANDS = {
    'help': '/help',
    'reset': '/reset',
    'attendance': '/attendance',
    'attendance_redo': '/attendance-redo',
    'end_session': '/end',
    'players': '/players',
    'qa': 'What is a good warm-up drill?',
}

EXPECTED_ALLOWED = {
    ('help', 'coach'): True, ('help', 'participant'): True,
    ('reset', 'coach'): True, ('reset', 'participant'): True,
    ('qa', 'coach'): True, ('qa', 'participant'): True,
    ('attendance', 'coach'): True, ('attendance', 'participant'): False,
    ('attendance_redo', 'coach'): True, ('attendance_redo', 'participant'): False,
    ('end_session', 'coach'): True, ('end_session', 'participant'): False,
    ('players', 'coach'): True, ('players', 'participant'): False,
}


@pytest.mark.parametrize('org_type', ['sports', 'ngo'])
@pytest.mark.parametrize('person_type', ['coach', 'participant'])
@pytest.mark.parametrize('command', list(TEXT_COMMANDS.keys()))
def test_command_gating_matrix(drive, org_type, person_type, command):
    text = TEXT_COMMANDS[command]
    reply = drive(org_type, person_type, text)

    allowed = EXPECTED_ALLOWED[(command, person_type)]

    if allowed:
        assert DECLINE_MARKER not in reply, (
            f"{person_type} should be ALLOWED to use '{command}' ({org_type} org), "
            f"but got the decline message: {reply!r}"
        )
    else:
        assert DECLINE_MARKER in reply, (
            f"{person_type} should be DECLINED for '{command}' ({org_type} org), "
            f"but got: {reply!r}"
        )


def test_command_permissions_map_matches_the_declared_allocation():
    """A structural guard on the permission map itself, independent of the
    behavioural matrix above — pins the exact allocation from the task:
    help/reset/qa open to both; attendance/attendance_redo/attendance_reply/
    end_session/players/photo_upload/location_checkin are coach-only."""
    coach_and_participant = {'coach', 'participant'}
    coach_only = {'coach'}

    assert ConversationService.COMMAND_PERMISSIONS['help'] == coach_and_participant
    assert ConversationService.COMMAND_PERMISSIONS['reset'] == coach_and_participant
    assert ConversationService.COMMAND_PERMISSIONS['qa'] == coach_and_participant

    for action in ('attendance', 'attendance_redo', 'attendance_reply',
                   'end_session', 'players', 'photo_upload', 'location_checkin'):
        assert ConversationService.COMMAND_PERMISSIONS[action] == coach_only, (
            f"Expected '{action}' to be coach-only per the task's allocation table."
        )


# ---------------------------------------------------------------------------
# Declines: terminology-driven, person-type-neutral, no cricket/sport words,
# no leaking of what the specific command was.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('org_type,expected_word', [('sports', 'coach'), ('ngo', 'facilitator')])
def test_decline_message_uses_org_terminology_not_hardcoded_word(drive, org_type, expected_word):
    reply = drive(org_type, 'participant', '/attendance')
    assert expected_word in reply.lower()
    if expected_word == 'facilitator':
        assert 'coach' not in reply.lower()


def test_decline_message_does_not_name_the_specific_command(drive):
    reply = drive('sports', 'participant', '/attendance')
    assert '/attendance' not in reply
    assert 'attendance' not in reply.lower()


def test_decline_message_has_no_cricket_or_sport_wording(drive):
    for command in ('/attendance', '/attendance-redo', '/end', '/players'):
        reply = drive('sports', 'participant', command)
        assert '🏏' not in reply
        assert 'cricket' not in reply.lower()


def test_decline_message_is_friendly_not_a_cryptic_error(drive):
    reply = drive('ngo', 'participant', '/players')
    assert 'error' not in reply.lower()
    assert DECLINE_MARKER in reply


# ---------------------------------------------------------------------------
# photo_upload / location_checkin: separate entry points (handle_image_
# message / handle_location_check_in), not text-command routing, but same
# permission map. location_checkin stays coach-only this step — participant
# self check-in is Phase 2 step 5.
# ---------------------------------------------------------------------------

@pytest.fixture
def drive_media(monkeypatch):
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda oid: {'id': oid, 'type': 'sports'})

    def _drive(handler_name, person_type, **kwargs):
        person = _person('org-sports', person_type)
        monkeypatch.setattr(PersonService, 'resolve', classmethod(lambda cls, phone: person))

        sent = {}

        def _fake_send(phone_number, message_text):
            sent['message_text'] = message_text
            return {'success': True}

        monkeypatch.setattr(WhatsAppService, 'send_message', _fake_send)

        handler = getattr(ConversationService, handler_name)
        handler(person['phone_number'], **kwargs)
        return sent.get('message_text')

    return _drive


@pytest.mark.parametrize('person_type,allowed', [('coach', True), ('participant', False)])
def test_photo_upload_gating(drive_media, person_type, allowed):
    reply = drive_media('handle_image_message', person_type, image_info={'id': 'media-1'}, message_id='m-1')
    if allowed:
        # A coach with no pending photo request gets the "no pending" reply,
        # not a decline — proving the permission gate let them through.
        assert DECLINE_MARKER not in reply
    else:
        assert DECLINE_MARKER in reply


@pytest.mark.parametrize('person_type,allowed', [('coach', True), ('participant', False)])
def test_location_checkin_gating(drive_media, person_type, allowed):
    reply = drive_media('handle_location_check_in', person_type, latitude=-26.2, longitude=28.0, message_id='m-2')
    if allowed:
        assert DECLINE_MARKER not in reply
    else:
        assert DECLINE_MARKER in reply


def test_location_checkin_still_coach_only_regression():
    """Explicit pin: participant self check-in is Phase 2 step 5, not this
    step — must not have been silently opened up."""
    assert ConversationService.COMMAND_PERMISSIONS['location_checkin'] == {'coach'}
