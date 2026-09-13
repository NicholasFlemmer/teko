"""Unit tests for the optional end-of-session photo + note flow that runs
after a coach sends /end (services/conversation_service.py).

Two new per-org boolean flags, both off by default, read with the existing
(org or {}).get('flag') or False idiom (same as missed_checkin_nudges at
scheduler_service.py:408-409 and attendance_mode at
conversation_service.py:910):

  - end_photo_prompt: ask for an end-of-session photo after /end
  - session_note_prompt: ask for a short session note after /end

Both are optional and skippable ("skip"). Pending state for each follows the
pending_photo pattern exactly (own collection, phone-keyed, created_at,
one-hour TTL, get/set/clear, PendingStateReadError distinguishes "read
failed" from "nothing pending").

Covers:
  - both flags off -> outbound message and Firestore write pinned exactly
    to what handle_end_session_command produced before this feature existed
  - photo on, note off: happy path (photo arrives) and skip
  - photo off, note on: happy path (note arrives) and skip
  - both on: full happy path (photo then note) and skip-at-each-step
  - note append when the session already has notes vs. write-as-is when empty
  - note text capped at 1000 characters, trimmed
  - pending_end_photo / pending_note expire after 3600s and are deleted on read
  - a /command during pending_note is handled as a command, not a note
    (and leaves pending_note untouched)
  - an org with no end_photo_prompt/session_note_prompt field at all behaves
    exactly like both flags off

Pure unit tests: PersonService, FirebaseService (sessions + organisation),
GeminiService, WhatsAppService and StorageService are all stubbed via
monkeypatch -- same convention as test_start_session.py and
test_headcount_attendance.py. Pending-state helpers (get/set/clear for
pending_end_photo and pending_note) are exercised for real against an
in-memory fake Firestore db, so the TTL/doc-shape tests prove the actual
implementation, not a mocked stand-in for it.

Usage:
    cd backend
    pytest tests/test_end_session_photo_note.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) now lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from services.person_service import PersonService  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
from services.gemini_service import GeminiService  # noqa: E402
from services.whatsapp_service import WhatsAppService  # noqa: E402
from services.storage_service import StorageService  # noqa: E402


# ---------------------------------------------------------------------------
# In-memory fake Firestore db -- same pattern as test_start_session.py's
# _FakeDb / test_headcount_attendance.py's _FakeDb, backing get_pending_
# end_photo/set_pending_end_photo/clear_pending_end_photo and the pending_
# note equivalents for real.
# ---------------------------------------------------------------------------

class _FakeDocSnapshot:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data)


class _FakeDocRef:
    def __init__(self, store, key):
        self._store = store
        self._key = key

    def get(self):
        return _FakeDocSnapshot(self._store.get(self._key))

    def set(self, data):
        self._store[self._key] = data

    def delete(self):
        self._store.pop(self._key, None)


class _FakeCollection:
    def __init__(self, store):
        self._store = store

    def document(self, key):
        return _FakeDocRef(self._store, key)


class _FakeDb:
    def __init__(self):
        self._collections = {}

    def collection(self, name):
        return _FakeCollection(self._collections.setdefault(name, {}))


@pytest.fixture
def fake_db(monkeypatch):
    db = _FakeDb()
    monkeypatch.setattr(FirebaseService, 'get_db', lambda: db)
    return db


# ---------------------------------------------------------------------------
# Coach / session / org helpers
# ---------------------------------------------------------------------------

FIXED_TODAY = '2026-06-15'
FIXED_NOW = datetime(2026, 6, 15, 15, 0, tzinfo=timezone.utc)


def _coach(org_id='org-a', coach_id='coach-1', phone='27821234567', name='Alex'):
    return {
        'id': coach_id,
        'org_id': org_id,
        'name': name,
        'phone_number': phone,
        'person_type': 'coach',
    }


def _session(session_id='session-1', org_id='org-a', team_id='team-1',
             coach_id='coach-1', **extra):
    data = {
        'id': session_id,
        'org_id': org_id,
        'team_id': team_id,
        'date': FIXED_TODAY,
        'start_time': '14:00',
        'type': 'practice',
        'status': 'checked_in',
        'coach_id': coach_id,
        'coach_check_ins': {coach_id: True},
        'attended_player_ids': ['p1', 'p2'],
    }
    data.update(extra)
    return data


def _set_org(monkeypatch, org_id='org-a', **flags):
    org = {'id': org_id, 'type': 'sports', **flags}
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda oid: dict(org) if oid == org_id else None)
    return org


# ---------------------------------------------------------------------------
# Stateful session backend -- get_all_sessions/get_session/update_session all
# share one dict, so /end's write and a later note-append both see the same
# document (mirrors how test_missed_checkin_nudges.py's _FakeSessionsStore
# lets a scheduler run see its own prior write).
# ---------------------------------------------------------------------------

@pytest.fixture
def backend(monkeypatch, fake_db):
    session_store = {}

    def _get_all_sessions(org_id, coach_id=None, **kw):
        return [
            dict(s) for s in session_store.values()
            if s.get('org_id') == org_id and (coach_id is None or s.get('coach_id') == coach_id)
        ]

    def _get_session(session_id, org_id):
        s = session_store.get(session_id)
        if not s:
            return None
        if org_id is not None and s.get('org_id') != org_id:
            return None
        return dict(s)

    def _update_session(session_id, data):
        session_store[session_id].update(data)
        return dict(session_store[session_id])

    monkeypatch.setattr(FirebaseService, 'get_all_sessions', _get_all_sessions)
    monkeypatch.setattr(FirebaseService, 'get_session', _get_session)
    monkeypatch.setattr(FirebaseService, 'update_session', _update_session)
    monkeypatch.setattr(FirebaseService, 'update_team', lambda tid, data: None)
    monkeypatch.setattr(FirebaseService, 'get_org_now', lambda org_id: FIXED_NOW)
    return session_store


@pytest.fixture
def drive(monkeypatch, backend):
    """Drive a WhatsApp text message through the real handle_incoming_message
    entry point."""
    monkeypatch.setattr(GeminiService, 'generate_custom_message', lambda prompt: "STUBBED AI REPLY")
    monkeypatch.setattr(ConversationService, 'get_conversation_history', classmethod(lambda cls, phone, limit=10: []))
    monkeypatch.setattr(ConversationService, 'save_message', classmethod(lambda cls, phone, role, content: None))
    monkeypatch.setattr(FirebaseService, 'get_all_content', lambda org_id: [])
    monkeypatch.setattr(FirebaseService, 'get_all_urls', lambda org_id: [])

    def _drive(coach, text):
        monkeypatch.setattr(PersonService, 'resolve', lambda phone: dict(coach))
        sent = {}

        def _fake_send(phone_number, message_text):
            sent['message_text'] = message_text
            return {'success': True}

        monkeypatch.setattr(WhatsAppService, 'send_message', _fake_send)
        ConversationService.handle_incoming_message(coach['phone_number'], text, message_id='end-flow-test')
        return sent.get('message_text')

    return _drive


class _FakeBlob:
    def upload_from_string(self, data, content_type=None):
        pass

    def generate_signed_url(self, expiration=None, method=None, credentials=None):
        # Real generate_signed_url() accepts a credentials= kwarg (used to
        # route signing through the IAM-impersonated credentials from
        # StorageService.get_signing_credentials() -- see
        # test_generate_signed_url_calls_are_passed_signing_credentials
        # below). Recording it here lets that test prove the real call
        # sites actually pass it, not just that a URL comes back.
        signed_url_calls.append({'credentials': credentials})
        return 'https://example.com/end-photo.jpg'


class _FakeBucket:
    def blob(self, path):
        return _FakeBlob()


signed_url_calls = []

# A recognisable sentinel standing in for the real signing-aware
# credentials StorageService.get_signing_credentials() would return
# (unit-tested directly in test_storage_signing_credentials.py). Fixed at
# module level so tests can assert the exact object identity was passed
# through to generate_signed_url(), not just that some credentials were.
SENTINEL_SIGNING_CREDENTIALS = object()


@pytest.fixture
def drive_image(monkeypatch, backend):
    """Drive a WhatsApp image message through the real handle_image_message
    entry point, with WhatsApp media download and Cloud Storage stubbed."""
    signed_url_calls.clear()
    monkeypatch.setattr(ConversationService, '_download_whatsapp_media',
                         classmethod(lambda cls, media_id: (b'fake-bytes', 'image/jpeg')))
    monkeypatch.setattr(StorageService, 'get_bucket', classmethod(lambda cls: _FakeBucket()))
    monkeypatch.setattr(StorageService, 'get_signing_credentials',
                         classmethod(lambda cls: SENTINEL_SIGNING_CREDENTIALS))

    def _drive(coach):
        monkeypatch.setattr(PersonService, 'resolve', lambda phone: dict(coach))
        sent = {}

        def _fake_send(phone_number, message_text):
            sent['message_text'] = message_text
            return {'success': True}

        monkeypatch.setattr(WhatsAppService, 'send_message', _fake_send)
        ConversationService.handle_image_message(coach['phone_number'], {'id': 'media-1'}, message_id='end-photo-test')
        return sent.get('message_text')

    return _drive


BOTH_OFF_MESSAGE = "✅ Session completed! (Practice at 14:00)\nAttendance: 2 players recorded\n\nGreat work, Coach! 🎉"


# ---------------------------------------------------------------------------
# 1. Both flags off -> exact same outbound message and write as before this
# feature existed.
# ---------------------------------------------------------------------------

def test_both_flags_off_pins_exact_message_and_write(drive, monkeypatch, backend):
    _set_org(monkeypatch, end_photo_prompt=False, session_note_prompt=False)
    backend['session-1'] = _session()
    coach = _coach()

    reply = drive(coach, '/end')

    assert reply == BOTH_OFF_MESSAGE
    assert backend['session-1']['status'] == 'completed'
    assert 'completed_at' in backend['session-1']
    assert ConversationService.get_pending_end_photo(coach['phone_number']) is None
    assert ConversationService.get_pending_note(coach['phone_number']) is None


def test_org_with_no_flag_field_at_all_behaves_as_off(drive, monkeypatch, backend):
    # No end_photo_prompt / session_note_prompt key at all -- not even
    # explicit False -- must behave identically to both-off.
    _set_org(monkeypatch)
    backend['session-1'] = _session()
    coach = _coach()

    reply = drive(coach, '/end')

    assert reply == BOTH_OFF_MESSAGE
    assert ConversationService.get_pending_end_photo(coach['phone_number']) is None
    assert ConversationService.get_pending_note(coach['phone_number']) is None


# ---------------------------------------------------------------------------
# 2. Photo on, note off.
# ---------------------------------------------------------------------------

def test_photo_on_note_off_prompts_for_photo(drive, monkeypatch, backend):
    _set_org(monkeypatch, end_photo_prompt=True, session_note_prompt=False)
    backend['session-1'] = _session()
    coach = _coach()

    reply = drive(coach, '/end')

    assert reply == (
        "✅ Session completed! (Practice at 14:00)\nAttendance: 2 players recorded\n\n"
        "📸 Got a photo from the end of the session? Send it over, or reply skip."
    )
    pending = ConversationService.get_pending_end_photo(coach['phone_number'])
    assert pending == {'session_id': 'session-1', 'team_id': 'team-1', 'created_at': pending['created_at']}


def test_photo_on_note_off_photo_arrives_finishes(drive, drive_image, monkeypatch, backend):
    _set_org(monkeypatch, end_photo_prompt=True, session_note_prompt=False)
    backend['session-1'] = _session()
    coach = _coach()

    drive(coach, '/end')
    reply = drive_image(coach)

    assert reply == "📸 End-of-session photo saved!\n\nGreat work, Coach! 🎉"
    assert ConversationService.get_pending_end_photo(coach['phone_number']) is None
    photos = backend['session-1']['photos']
    assert len(photos) == 1
    assert photos[0]['phase'] == 'end'
    assert photos[0]['url'] == 'https://example.com/end-photo.jpg'
    assert photos[0]['uploaded_by'] == 'coach-1'
    # group_photo / latest_group_photo (the check-in path) are untouched --
    # this was an end-of-session photo, not a check-in photo.
    assert 'group_photo' not in backend['session-1']


def test_photo_on_note_off_skip_finishes(drive, monkeypatch, backend):
    _set_org(monkeypatch, end_photo_prompt=True, session_note_prompt=False)
    backend['session-1'] = _session()
    coach = _coach()

    drive(coach, '/end')
    reply = drive(coach, 'skip')

    assert reply == "No worries — skipping the end-of-session photo.\n\nGreat work, Coach! 🎉"
    assert ConversationService.get_pending_end_photo(coach['phone_number']) is None
    assert 'photos' not in backend['session-1']


# ---------------------------------------------------------------------------
# 3. Photo off, note on.
# ---------------------------------------------------------------------------

def test_photo_off_note_on_prompts_for_note(drive, monkeypatch, backend):
    _set_org(monkeypatch, end_photo_prompt=False, session_note_prompt=True)
    backend['session-1'] = _session()
    coach = _coach()

    reply = drive(coach, '/end')

    assert reply == (
        "✅ Session completed! (Practice at 14:00)\nAttendance: 2 players recorded\n\n"
        "📝 Want to leave a quick note about this session? Reply with a short note, or reply skip."
    )
    pending = ConversationService.get_pending_note(coach['phone_number'])
    assert pending['session_id'] == 'session-1'
    assert ConversationService.get_pending_end_photo(coach['phone_number']) is None


def test_photo_off_note_on_note_arrives_saves_and_finishes(drive, monkeypatch, backend):
    _set_org(monkeypatch, end_photo_prompt=False, session_note_prompt=True)
    backend['session-1'] = _session()
    coach = _coach()

    drive(coach, '/end')
    reply = drive(coach, 'Great session, worked on passing drills')

    assert reply == "Got it, thanks — note saved!\n\nGreat work, Coach! 🎉"
    assert backend['session-1']['notes'] == 'Great session, worked on passing drills'
    assert ConversationService.get_pending_note(coach['phone_number']) is None


def test_photo_off_note_on_skip_finishes_without_saving(drive, monkeypatch, backend):
    _set_org(monkeypatch, end_photo_prompt=False, session_note_prompt=True)
    backend['session-1'] = _session()
    coach = _coach()

    drive(coach, '/end')
    reply = drive(coach, 'skip')

    assert reply == "No worries — skipping the note.\n\nGreat work, Coach! 🎉"
    assert 'notes' not in backend['session-1']
    assert ConversationService.get_pending_note(coach['phone_number']) is None


# ---------------------------------------------------------------------------
# 4. Both on: full happy path (photo then note), and skip at each step.
# ---------------------------------------------------------------------------

def test_both_on_full_happy_path(drive, drive_image, monkeypatch, backend):
    _set_org(monkeypatch, end_photo_prompt=True, session_note_prompt=True)
    backend['session-1'] = _session()
    coach = _coach()

    r1 = drive(coach, '/end')
    assert r1.endswith("📸 Got a photo from the end of the session? Send it over, or reply skip.")

    r2 = drive_image(coach)
    assert r2 == (
        "📸 End-of-session photo saved!\n\n"
        "📝 Want to leave a quick note about this session? Reply with a short note, or reply skip."
    )
    # Bug fix: handle_image_message's end-of-session-photo branch must pass
    # StorageService.get_signing_credentials() through to
    # generate_signed_url(), not call it with the raw default/unsigned
    # credentials (which raise AttributeError on Cloud Run -- see
    # conversation_service.py's two generate_signed_url call sites).
    assert signed_url_calls[-1]['credentials'] is SENTINEL_SIGNING_CREDENTIALS, (
        "generate_signed_url() must be called with StorageService.get_signing_credentials(), "
        "not left to the default (unsigned) credentials"
    )
    assert ConversationService.get_pending_end_photo(coach['phone_number']) is None
    pending_note = ConversationService.get_pending_note(coach['phone_number'])
    assert pending_note['session_id'] == 'session-1'

    r3 = drive(coach, 'Good energy today')
    assert r3 == "Got it, thanks — note saved!\n\nGreat work, Coach! 🎉"
    assert backend['session-1']['notes'] == 'Good energy today'
    assert backend['session-1']['photos'][0]['phase'] == 'end'
    assert ConversationService.get_pending_note(coach['phone_number']) is None


def test_both_on_skip_at_each_step(drive, monkeypatch, backend):
    _set_org(monkeypatch, end_photo_prompt=True, session_note_prompt=True)
    backend['session-1'] = _session()
    coach = _coach()

    drive(coach, '/end')
    r2 = drive(coach, 'skip')
    assert r2 == (
        "No worries — skipping the end-of-session photo.\n\n"
        "📝 Want to leave a quick note about this session? Reply with a short note, or reply skip."
    )
    assert ConversationService.get_pending_end_photo(coach['phone_number']) is None
    assert ConversationService.get_pending_note(coach['phone_number']) is not None

    r3 = drive(coach, 'skip')
    assert r3 == "No worries — skipping the note.\n\nGreat work, Coach! 🎉"
    assert 'notes' not in backend['session-1']
    assert ConversationService.get_pending_note(coach['phone_number']) is None


# ---------------------------------------------------------------------------
# 5. Note append vs. write-as-is, and the 1000-char cap.
# ---------------------------------------------------------------------------

def test_note_appends_when_session_already_has_notes(drive, monkeypatch, backend):
    _set_org(monkeypatch, end_photo_prompt=False, session_note_prompt=True)
    backend['session-1'] = _session(notes='Pre-existing note from admin')
    coach = _coach()

    drive(coach, '/end')
    drive(coach, 'Ball skills improved')

    assert backend['session-1']['notes'] == (
        'Pre-existing note from admin\nCoach note: Ball skills improved'
    )


def test_note_written_as_is_when_session_has_no_notes(drive, monkeypatch, backend):
    _set_org(monkeypatch, end_photo_prompt=False, session_note_prompt=True)
    backend['session-1'] = _session()
    coach = _coach()

    drive(coach, '/end')
    drive(coach, 'Ball skills improved')

    assert backend['session-1']['notes'] == 'Ball skills improved'


def test_note_capped_at_1000_characters_and_trimmed(drive, monkeypatch, backend):
    _set_org(monkeypatch, end_photo_prompt=False, session_note_prompt=True)
    backend['session-1'] = _session()
    coach = _coach()

    long_text = '   ' + ('x' * 1200) + '   '
    drive(coach, '/end')
    drive(coach, long_text)

    assert backend['session-1']['notes'] == 'x' * 1000


# ---------------------------------------------------------------------------
# 6. pending_end_photo / pending_note expire after 3600s and are deleted on
# read (same TTL/one-hour contract as pending_photo).
# ---------------------------------------------------------------------------

def test_pending_end_photo_expires_after_3600s_and_is_deleted_on_read(fake_db):
    phone = '27821234567'
    key = ConversationService._phone_key(phone)
    stale_created_at = datetime.now(timezone.utc) - timedelta(seconds=3601)
    fake_db.collection('pending_end_photo').document(key).set({
        'session_id': 'session-1', 'team_id': 'team-1', 'created_at': stale_created_at,
    })

    result = ConversationService.get_pending_end_photo(phone)

    assert result is None
    assert fake_db.collection('pending_end_photo').document(key).get().exists is False


def test_pending_end_photo_not_yet_expired_is_returned(fake_db):
    phone = '27821234567'
    key = ConversationService._phone_key(phone)
    fresh_created_at = datetime.now(timezone.utc) - timedelta(seconds=60)
    fake_db.collection('pending_end_photo').document(key).set({
        'session_id': 'session-1', 'team_id': 'team-1', 'created_at': fresh_created_at,
    })

    result = ConversationService.get_pending_end_photo(phone)

    assert result is not None
    assert result['session_id'] == 'session-1'


def test_pending_note_expires_after_3600s_and_is_deleted_on_read(fake_db):
    phone = '27821234567'
    key = ConversationService._phone_key(phone)
    stale_created_at = datetime.now(timezone.utc) - timedelta(seconds=3601)
    fake_db.collection('pending_note').document(key).set({
        'session_id': 'session-1', 'created_at': stale_created_at,
    })

    result = ConversationService.get_pending_note(phone)

    assert result is None
    assert fake_db.collection('pending_note').document(key).get().exists is False


def test_pending_note_not_yet_expired_is_returned(fake_db):
    phone = '27821234567'
    key = ConversationService._phone_key(phone)
    fresh_created_at = datetime.now(timezone.utc) - timedelta(seconds=60)
    fake_db.collection('pending_note').document(key).set({
        'session_id': 'session-1', 'created_at': fresh_created_at,
    })

    result = ConversationService.get_pending_note(phone)

    assert result is not None
    assert result['session_id'] == 'session-1'


# ---------------------------------------------------------------------------
# 7. A /command during pending_note is handled as a command, not a note --
# and leaves pending_note untouched (not consumed).
# ---------------------------------------------------------------------------

def test_command_during_pending_note_is_handled_as_command(drive, monkeypatch, backend):
    _set_org(monkeypatch, end_photo_prompt=False, session_note_prompt=True)
    backend['session-1'] = _session()
    coach = _coach()

    drive(coach, '/end')
    reply = drive(coach, '/help')

    assert 'Commands:' in reply
    assert 'note saved' not in reply.lower()
    assert 'notes' not in backend['session-1']
    # Not consumed -- the pending note request is still there afterwards.
    assert ConversationService.get_pending_note(coach['phone_number']) is not None


def test_command_during_pending_end_photo_is_handled_as_command(drive, monkeypatch, backend):
    _set_org(monkeypatch, end_photo_prompt=True, session_note_prompt=False)
    backend['session-1'] = _session()
    coach = _coach()

    drive(coach, '/end')
    reply = drive(coach, '/help')

    assert 'Commands:' in reply
    assert ConversationService.get_pending_end_photo(coach['phone_number']) is not None


# ---------------------------------------------------------------------------
# 8. Non-skip, non-command text during pending_end_photo re-prompts and
# leaves the pending request in place (not required by the task, but a
# cheap, real behaviour worth pinning).
# ---------------------------------------------------------------------------

def test_free_text_during_pending_end_photo_reprompts(drive, monkeypatch, backend):
    _set_org(monkeypatch, end_photo_prompt=True, session_note_prompt=False)
    backend['session-1'] = _session()
    coach = _coach()

    drive(coach, '/end')
    reply = drive(coach, 'sure, one sec')

    assert reply == "📸 Got a photo from the end of the session? Send it over, or reply skip."
    assert ConversationService.get_pending_end_photo(coach['phone_number']) is not None
