"""Tests for the org-scoping fix on the SSE coach-activity feed
(routes/sse.py). Before this fix, the feed had no role gate at all (any
valid JWT of any role passed) and no org scoping whatsoever (every reader
saw every org's events from one shared in-memory buffer).

Covers:
  - a coach-role token is rejected (403) -- only super_admin/location_admin
    may read this feed
  - a token with no role claim at all is rejected (403), matching the
    fail-closed posture in routes/auth.py's role_required()
  - a token with no org_id claim is rejected (403) rather than falling
    through to an unscoped read
  - a reader only receives events pushed for their own org, never another
    org's events, even when both are in the shared buffer
  - the attendance push_event call site (the one that has no org_id
    already in scope, and does a deliberate unscoped single-document
    session lookup to find it) skips pushing entirely -- rather than
    pushing with org_id=None -- when that session can't be found or has
    no org_id of its own

Pure unit tests: the HTTP-level tests use a minimal Flask app registering
only sse_bp (same convention as test_check_in.py), so importing this file
never triggers app.py's module-level FirebaseService.initialize()/scheduler
start. The buffer-filtering test calls routes.sse._stream_generator()
directly rather than over HTTP, since the route wraps it in a real
streaming Response. The attendance-skip test calls
ConversationService.handle_attendance_response() directly with
FirebaseService/PersonService stubbed via monkeypatch.

Usage:
    cd backend
    pytest tests/test_sse_scoping.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv  # noqa: E402

STAGING_ENV_PATH = os.path.join(os.path.dirname(__file__), '..', '.env.staging')
if os.path.exists(STAGING_ENV_PATH):
    load_dotenv(dotenv_path=STAGING_ENV_PATH, override=True)
    os.environ['FIREBASE_CREDENTIALS_PATH'] = ''

from datetime import datetime, timedelta, timezone  # noqa: E402

import jwt as _jwt  # noqa: E402
import pytest  # noqa: E402
from flask import Flask  # noqa: E402

from config import Config  # noqa: E402
from routes import sse as sse_module  # noqa: E402
from routes.sse import sse_bp  # noqa: E402
import services.conversation_service as conversation_service_module  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
from services.person_service import PersonService  # noqa: E402


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(sse_bp, url_prefix='/api/sse')
    app.testing = True
    return app.test_client()


def _make_token(role=None, org_id='org-a', include_role_claim=True, include_org_id_claim=True):
    """Mint a JWT the same way auth.py's login()/refresh_token() do.

    include_role_claim=False / include_org_id_claim=False omit that key
    entirely, simulating a token that never had the claim rather than one
    carrying an explicit None.
    """
    payload = {
        'username': 'test-user',
        'exp': datetime.now(timezone.utc) + timedelta(hours=1),
    }
    if include_role_claim:
        payload['role'] = role
    if include_org_id_claim:
        payload['org_id'] = org_id
    return _jwt.encode(payload, Config.SECRET_KEY, algorithm='HS256')


def test_coach_role_token_is_rejected(client):
    token = _make_token(role='coach', org_id='org-a')

    resp = client.get(f'/api/sse/coach-activity?token={token}')

    assert resp.status_code == 403


def test_token_with_no_role_claim_is_rejected(client):
    token = _make_token(include_role_claim=False, org_id='org-a')

    resp = client.get(f'/api/sse/coach-activity?token={token}')

    assert resp.status_code == 403


def test_token_with_no_org_id_claim_is_rejected(client):
    """super_admin included -- there is no unscoped-read escape hatch on
    this feed for any role, unlike FirebaseService's org_id=None
    super_admin cross-org read pattern elsewhere in the codebase."""
    token = _make_token(role='super_admin', include_org_id_claim=False)

    resp = client.get(f'/api/sse/coach-activity?token={token}')

    assert resp.status_code == 403


def test_reader_does_not_receive_another_orgs_events(monkeypatch):
    """Two events land in the shared buffer, one per org. A reader scoped
    to org-a must only ever see org-a's event out of _stream_generator,
    never org-b's."""
    sse_module._event_list.clear()
    sse_module._trim_offset = 0

    call_count = {'n': 0}

    def _fake_sleep(seconds):
        # Push both events on the generator's first sleep, simulating
        # both orgs producing activity between poll iterations. org-b is
        # pushed FIRST deliberately: next(gen) only observes the single
        # earliest yielded item, so if the filter were removed the
        # unfiltered list would yield org-b's event first and this
        # assertion would actually catch it -- pushing org-a first would
        # make org-a's event the first yield regardless of whether
        # filtering happened at all, making the test vacuous.
        call_count['n'] += 1
        if call_count['n'] == 1:
            sse_module.push_event('message_received', org_id='org-b', preview='hello from B')
            sse_module.push_event('message_received', org_id='org-a', preview='hello from A')

    monkeypatch.setattr(sse_module.time, 'sleep', _fake_sleep)

    gen = sse_module._stream_generator('org-a')
    output = next(gen)

    assert 'hello from A' in output
    assert 'hello from B' not in output


class _FakeDocRef:
    def delete(self):
        pass

    def set(self, data):
        pass


class _FakeCollection:
    def document(self, key):
        return _FakeDocRef()


class _FakeDb:
    def collection(self, name):
        return _FakeCollection()


def test_attendance_event_skipped_when_session_has_no_org_id(monkeypatch, caplog):
    """handle_attendance_response has no org_id of its own in scope -- it
    does a deliberate unscoped single-document lookup (get_session(...,
    None)) purely to find the org_id for the dashboard event. If that
    session can't be found, or exists but has no org_id, the event must
    be skipped entirely -- never pushed with org_id=None, which would
    just be silently invisible to every reader instead of loudly absent.
    Attendance itself must still be recorded either way."""
    pushed = []
    monkeypatch.setattr(conversation_service_module, 'push_event',
                         lambda *a, **kw: pushed.append((a, kw)))
    monkeypatch.setattr(PersonService, 'resolve', lambda phone: None)
    monkeypatch.setattr(FirebaseService, 'get_session',
                         lambda session_id, org_id: {'id': session_id})  # no 'org_id' key at all
    saved = []
    monkeypatch.setattr(FirebaseService, 'update_session',
                         lambda session_id, data: saved.append((session_id, data)))
    monkeypatch.setattr(FirebaseService, 'get_db', lambda: _FakeDb())

    pending = {
        'session_id': 'sess-no-org',
        'players': [
            {'id': 'p1', 'number': 1, 'name': 'Alice'},
            {'id': 'p2', 'number': 2, 'name': 'Bob'},
        ],
    }

    with caplog.at_level('WARNING'):
        result = ConversationService.handle_attendance_response('27821234567', 'all', pending)

    assert pushed == [], "must not push an event when org_id can't be resolved"
    assert saved == [('sess-no-org', {'attended_player_ids': ['p1', 'p2']})], \
        "attendance must still be recorded even when the dashboard event is skipped"
    assert any('sess-no-org' in r.message for r in caplog.records), \
        "must log a warning naming the session id"
    assert '2/2' in result or 'Attendance recorded' in result
