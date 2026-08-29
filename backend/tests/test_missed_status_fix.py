"""Regression tests for two bugs that caused sessions with real coach
check-ins to be overwritten as 'missed'.

Ported from fix-missed-status-overwrite (commit 258bcb0, off
prod-reconcile) onto phase2-participant-identity, where get_session takes
an org_id parameter. The two fixed code paths are otherwise identical on
both branches -- check_in_session() requires an org_id and threads it
straight into get_session(session_id, org_id) (the tests below pass a
fixed dummy org_id since the fake get_session ignores it), and
mark_missed_sessions() never took an org_id at all.

Bug 1 (services/firebase_service.py, check_in_session): on a multi-coach
session, when some but not all assigned coaches had checked in, status was
left unchanged ('reminded') instead of being set to 'checked_in'.

Bug 2 (services/scheduler_service.py, mark_missed_sessions): the sweep
unconditionally set status='missed' once a session's end time had passed,
without ever checking coach_check_ins or check_in_time -- so it overwrote
genuine partial check-ins as missed.

Pure unit tests: FirebaseService.get_db/get_session/update_session are
monkeypatched with in-memory fakes (same convention as test_check_in.py),
so nothing here touches Firestore.

Usage:
    cd backend
    FIREBASE_PROJECT_ID=teko-staging-tgh pytest tests/test_missed_status_fix.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) now lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402

from services.firebase_service import FirebaseService  # noqa: E402
from services.scheduler_service import SchedulerService  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes for services.scheduler_service.mark_missed_sessions
# ---------------------------------------------------------------------------

class _FakeDoc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return self._data


class _FakeQueryable:
    """Stands in for db.collection('sessions').where(...).stream()."""

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


def _install_fake_sessions(monkeypatch, sessions):
    """sessions: list of dicts (each must include 'id'); served as the
    'reminded' query result. Captures every FirebaseService.update_session
    call as (session_id, data) tuples.

    mark_missed_sessions() never takes an org_id, so this fake matches
    update_session(session_id, data) verbatim on this branch too.
    """
    docs = [_FakeDoc(s['id'], {k: v for k, v in s.items() if k != 'id'}) for s in sessions]
    fake_db = _FakeDb(docs)
    monkeypatch.setattr(FirebaseService, 'get_db', lambda: fake_db)

    captured = []

    def fake_update_session(session_id, data):
        captured.append((session_id, data))
        return None

    monkeypatch.setattr(FirebaseService, 'update_session', fake_update_session)
    return captured


def _past_session(session_id='sess-past', **extra):
    """A session whose end_time is safely in the past relative to real now.

    No org_id is set on these fixtures, so mark_missed_sessions resolves
    "now" via FirebaseService.get_org_now(None), which falls back to UTC --
    build against that same clock.
    """
    end = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
    start = end - timedelta(hours=1)
    session = {
        'id': session_id,
        'status': 'reminded',
        'date': end.strftime('%Y-%m-%d'),
        'start_time': start.strftime('%H:%M'),
        'end_time': end.strftime('%H:%M'),
    }
    session.update(extra)
    return session


def _future_session(session_id='sess-future', **extra):
    """A session whose end_time is safely in the future relative to real now.

    Same no-org_id -> UTC fallback reasoning as _past_session above.
    """
    start = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
    end = start + timedelta(hours=1)
    session = {
        'id': session_id,
        'status': 'reminded',
        'date': end.strftime('%Y-%m-%d'),
        'start_time': start.strftime('%H:%M'),
        'end_time': end.strftime('%H:%M'),
    }
    session.update(extra)
    return session


# ---------------------------------------------------------------------------
# mark_missed_sessions
# ---------------------------------------------------------------------------

def test_mark_missed_no_check_in_evidence_is_marked_missed(monkeypatch):
    session = _past_session()
    captured = _install_fake_sessions(monkeypatch, [session])

    result = SchedulerService.mark_missed_sessions()

    assert result['success'] is True
    assert captured == [(session['id'], {'status': 'missed'})]


def test_mark_missed_with_coach_check_ins_is_rescued_to_checked_in(monkeypatch):
    session = _past_session(coach_check_ins={'coach-1': {'check_in_time': 'x'}})
    captured = _install_fake_sessions(monkeypatch, [session])

    result = SchedulerService.mark_missed_sessions()

    assert result['success'] is True
    assert captured == [(session['id'], {'status': 'checked_in'})]


def test_mark_missed_with_check_in_time_but_no_coach_check_ins_is_rescued(monkeypatch):
    session = _past_session(check_in_time='2026-08-15T10:00:00Z', coach_check_ins={})
    captured = _install_fake_sessions(monkeypatch, [session])

    result = SchedulerService.mark_missed_sessions()

    assert result['success'] is True
    assert captured == [(session['id'], {'status': 'checked_in'})]


def test_mark_missed_session_not_past_end_time_is_untouched(monkeypatch):
    session = _future_session()
    captured = _install_fake_sessions(monkeypatch, [session])

    result = SchedulerService.mark_missed_sessions()

    assert result['success'] is True
    assert captured == []
    assert result['sessions_marked_missed'] == 0


# ---------------------------------------------------------------------------
# check_in_session
# ---------------------------------------------------------------------------

def _install_check_in_fakes(monkeypatch, session):
    """Monkeypatch FirebaseService.get_db/get_session for check_in_session.
    Captures the update_data written to sessions/{session_id} via
    doc_ref.update(...).

    check_in_session() now requires org_id and passes it straight into
    cls.get_session(session_id, org_id), so the fake matches that two-arg
    signature -- same convention as test_check_in.py. The tests below pass
    a fixed dummy org_id; this file is about the status-transition logic,
    not org scoping, and the fake get_session ignores the value anyway.
    """
    captured = []

    class _FakeDocRef:
        def __init__(self, session_id):
            self.session_id = session_id

        def update(self, data):
            captured.append((self.session_id, data))

    class _FakeCollection:
        def document(self, session_id):
            return _FakeDocRef(session_id)

    class _FakeDb:
        def collection(self, name):
            assert name == 'sessions'
            return _FakeCollection()

    monkeypatch.setattr(FirebaseService, 'get_db', lambda: _FakeDb())
    monkeypatch.setattr(FirebaseService, 'get_session', lambda session_id, org_id: dict(session))
    return captured


def test_check_in_multi_coach_two_of_five_checked_in_sets_checked_in(monkeypatch):
    session = {
        'id': 'sess-1',
        'status': 'reminded',
        'coach_ids': ['c1', 'c2', 'c3', 'c4', 'c5'],
        'coach_check_ins': {'c1': True},
    }
    captured = _install_check_in_fakes(monkeypatch, session)

    FirebaseService.check_in_session('sess-1', {'location_verified': True, 'location': {}}, org_id='org-1', coach_id='c2')

    assert len(captured) == 1
    _, update_data = captured[0]
    assert update_data['status'] == 'checked_in'


def test_check_in_multi_coach_all_checked_in_sets_checked_in_unchanged(monkeypatch):
    session = {
        'id': 'sess-1',
        'status': 'reminded',
        'coach_ids': ['c1', 'c2'],
        'coach_check_ins': {'c1': True},
    }
    captured = _install_check_in_fakes(monkeypatch, session)

    FirebaseService.check_in_session('sess-1', {'location_verified': True, 'location': {}}, org_id='org-1', coach_id='c2')

    assert len(captured) == 1
    _, update_data = captured[0]
    assert update_data['status'] == 'checked_in'


def test_check_in_single_coach_location_verified_true_sets_checked_in(monkeypatch):
    session = {
        'id': 'sess-1',
        'status': 'reminded',
        'coach_id': 'c1',
    }
    captured = _install_check_in_fakes(monkeypatch, session)

    FirebaseService.check_in_session('sess-1', {'location_verified': True, 'location': {}}, org_id='org-1', coach_id='c1')

    assert len(captured) == 1
    _, update_data = captured[0]
    assert update_data['status'] == 'checked_in'


def test_check_in_single_coach_location_verified_false_sets_missed(monkeypatch):
    """PINNED BEHAVIOUR -- deliberately not changed by this fix.

    A single/unknown-coach check-in with location_verified=False still
    writes status='missed', even though a real check-in attempt happened.
    That is bug-shaped but is a separate, undecided product question
    (should a failed-GPS check-in count as an attendance signal?) and is
    explicitly out of scope here per DECIDED BEHAVIOUR. Do not "fix" this
    test without a product decision on Bucket A behaviour.
    """
    session = {
        'id': 'sess-1',
        'status': 'reminded',
        'coach_id': 'c1',
    }
    captured = _install_check_in_fakes(monkeypatch, session)

    FirebaseService.check_in_session('sess-1', {'location_verified': False, 'location': {}}, org_id='org-1', coach_id='c1')

    assert len(captured) == 1
    _, update_data = captured[0]
    assert update_data['status'] == 'missed'
