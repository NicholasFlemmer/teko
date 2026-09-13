"""Unit tests for same-day multi-session resolution in /attendance.

Bug: _handle_attendance_command_inner (and handle_attendance_redo) used to
pick "today's session" for a coach by sorting all of today's sessions by
start_time and taking the first, unconditionally -- so a coach with more
than one session today always locked onto the earliest one, even if it had
long since ended, instead of whichever session was actually happening now.
This misrouted /attendance, headcount/attendance recording, and the
resulting pending_photo handoff onto the wrong session.

Fix: ConversationService._select_active_or_nearest_session prefers, in
order: (1) a session currently in its time window (start_time <= org_now
<= end_time, end_time defaulting to start_time + 2h -- same convention as
scheduler_service), (2) the session whose start_time is closest to org_now
when none are active, (3) the old sort-by-start_time behaviour is
unaffected when there's only one session today.

These tests exercise the fix through the public /attendance entry point
(handle_attendance_command, attendance_mode='headcount') so they prove the
real user-facing symptom is fixed, not just the helper in isolation.

Usage:
    cd backend
    pytest tests/test_session_selection.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402


# ---------------------------------------------------------------------------
# Fake Firestore db, same minimal pattern as test_headcount_attendance.py,
# just enough to back pending_headcount storage for real.
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


def _coach(org_id='org-a', coach_id='coach-1', phone='27821234567', name='Alex'):
    return {
        'id': coach_id,
        'org_id': org_id,
        'name': name,
        'phone_number': phone,
        'person_type': 'coach',
    }


def _org():
    return {'id': 'org-a', 'type': 'sports', 'attendance_mode': 'headcount'}


def _session(session_id, start_time, end_time, headcount=None, date_str='2026-09-13'):
    s = {
        'id': session_id,
        'org_id': 'org-a',
        'team_id': 'team-1',
        'date': date_str,
        'start_time': start_time,
        'end_time': end_time,
        'type': 'practice',
        'coach_id': 'coach-1',
        'coach_ids': ['coach-1'],
    }
    if headcount is not None:
        s['headcount'] = headcount
    return s


def _wire_common(monkeypatch, sessions, org_now):
    monkeypatch.setattr(FirebaseService, 'get_org_now', lambda org_id: org_now)
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org())
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: sessions)
    monkeypatch.setattr(FirebaseService, 'get_team', lambda team_id, org_id: {'id': team_id, 'name': 'Sub-15'})

    def _boom(*a, **kw):
        raise AssertionError("headcount mode must never call get_all_players")
    monkeypatch.setattr(FirebaseService, 'get_all_players', _boom)


# ---------------------------------------------------------------------------
# 1. Two sessions today: one already ended (headcount recorded), one
#    currently in progress. /attendance must resolve to the in-progress one.
# ---------------------------------------------------------------------------

def test_attendance_resolves_to_in_progress_session_not_earlier_ended_one(monkeypatch, fake_db):
    ended = _session('session-earlier', '08:00', '10:00',
                      headcount={'boys': 5, 'girls': 2, 'new_participants': 0, 'total': 7})
    in_progress = _session('session-current', '13:00', '15:00')  # no headcount yet
    org_now = datetime(2026, 9, 13, 14, 0)  # inside session-current's window

    _wire_common(monkeypatch, [ended, in_progress], org_now)

    coach = _coach()
    reply = ConversationService.handle_attendance_command(coach)

    # If it had picked the earlier (ended) session, this would say
    # "already recorded" with a total of 7. It must instead prompt fresh
    # for the in-progress session, which has no headcount yet.
    assert 'already recorded' not in reply.lower(), reply
    assert 'boys' in reply.lower()

    pending = ConversationService.get_pending_headcount(coach['phone_number'])
    assert pending is not None
    assert pending['session_id'] == 'session-current', (
        f"expected pending_headcount to target the in-progress session, got {pending['session_id']!r}"
    )


# ---------------------------------------------------------------------------
# 2. Two sessions today, neither currently active: one already ended, one
#    still upcoming. Must pick whichever is closest in time to org_now, not
#    just the earliest.
# ---------------------------------------------------------------------------

def test_attendance_resolves_to_nearest_session_when_none_active(monkeypatch, fake_db):
    earlier_ended = _session('session-a', '08:00', '10:00')  # ended 5h before org_now
    later_upcoming = _session('session-b', '16:00', '18:00')  # starts 1h after org_now
    org_now = datetime(2026, 9, 13, 15, 0)  # between the two, closer to session-b

    _wire_common(monkeypatch, [earlier_ended, later_upcoming], org_now)

    coach = _coach()
    ConversationService.handle_attendance_command(coach)

    pending = ConversationService.get_pending_headcount(coach['phone_number'])
    assert pending is not None
    assert pending['session_id'] == 'session-b', (
        f"expected the nearest-in-time session (session-b), got {pending['session_id']!r} "
        "-- picking the earliest (session-a) would be the pre-fix bug"
    )


# ---------------------------------------------------------------------------
# 3. Single session today: behaviour is unchanged (regression guard).
# ---------------------------------------------------------------------------

def test_attendance_single_session_today_unchanged(monkeypatch, fake_db):
    only = _session('session-only', '10:00', '12:00')
    org_now = datetime(2026, 9, 13, 9, 0)  # before the session even starts

    _wire_common(monkeypatch, [only], org_now)

    coach = _coach()
    ConversationService.handle_attendance_command(coach)

    pending = ConversationService.get_pending_headcount(coach['phone_number'])
    assert pending is not None
    assert pending['session_id'] == 'session-only'
