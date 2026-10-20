"""A WhatsApp location check-in outside the venue radius leaves the session
'checked_in' (unverified), not 'missed'.

Covers, through handle_location_check_in with the REAL check_in_session over
an in-memory stand-in for the sessions collection:
  - first share outside the radius: distance stored, verified False,
    status 'checked_in', coach told to move closer and share again
  - retry inside the radius: verified True, status stays 'checked_in'
  - retry still outside: distance updated, still 'checked_in', unverified
  - verified check-in: nothing written
  - session with no venue: unchanged ('checked_in', unverifiable)
  - the attempt record from the earlier change is still written
and the missed-marking sweep:
  - never turns a session with a recorded check-in into 'missed', whatever
    its verified value, including when the check-in lands after the sweep
    read its snapshot (atomic helper)
  - the reminder's web check-in link path is unchanged (still 'missed' when
    outside the radius) -- the two routes now deliberately differ.

Pure unit tests: Firestore is stubbed.

Usage:
    cd backend
    pytest tests/test_unverified_checkin_status.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import date, datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402

from services import firebase_service as fb_mod  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
from services.person_service import PersonService  # noqa: E402
from services.scheduler_service import SchedulerService  # noqa: E402
from services.whatsapp_service import WhatsAppService  # noqa: E402

VENUE = {'latitude': -33.9, 'longitude': 18.4, 'radius': 100}
AT_VENUE = (-33.9, 18.4)
FAR = (-33.91, 18.4)      # about 1.1 km south
FARTHER = (-33.92, 18.4)  # about 2.2 km south


class Store:
    """In-memory sessions collection with dotted-key updates."""

    def __init__(self, session):
        self.doc = dict(session)
        self.writes = []

    def get(self, *_a, **_k):
        return dict(self.doc)

    def update(self, data):
        self.writes.append(dict(data))
        for k, v in data.items():
            if '.' in k:
                top, sub = k.split('.', 1)
                d = dict(self.doc.get(top) or {})
                d[sub] = v
                self.doc[top] = d
            else:
                self.doc[k] = v


class _Doc:
    def __init__(self, store): self.store = store
    def update(self, data): self.store.update(data)


class _Db:
    def __init__(self, store): self.store = store
    def collection(self, name): return self
    def document(self, doc_id): return _Doc(self.store)


def _session(check_in=None, location_id='loc-1', status='reminded'):
    s = {'id': 'sess-1', 'date': date.today().strftime('%Y-%m-%d'), 'status': status,
         'coach_ids': ['coach-1'], 'coach_id': 'coach-1',
         'coach_check_ins': {'coach-1': check_in} if check_in is not None else {}}
    if location_id:
        s['location_id'] = location_id
    return s


@pytest.fixture
def share(monkeypatch):
    """share(store, (lat, lng)) -> (message, attempts) using the real check_in_session."""
    def _share(store, where):
        coach = {'id': 'coach-1', 'org_id': 'org-a', 'name': 'Coach A', 'phone_number': '0821234567', 'person_type': 'coach'}
        monkeypatch.setattr(PersonService, 'resolve', lambda phone: dict(coach))
        monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [store.get()])
        monkeypatch.setattr(FirebaseService, 'get_org_now', lambda org_id: datetime.now())
        monkeypatch.setattr(FirebaseService, 'get_location',
                            lambda lid, org: dict(VENUE) if lid == 'loc-1' else None)
        monkeypatch.setattr(FirebaseService, 'get_session', lambda sid, org_id: store.get())
        monkeypatch.setattr(FirebaseService, 'get_db', classmethod(lambda cls: _Db(store)))
        attempts, sent = [], {}
        monkeypatch.setattr(FirebaseService, 'append_check_in_attempt',
                            lambda sid, attempt, org_id: attempts.append(attempt))
        monkeypatch.setattr(WhatsAppService, 'send_message',
                            lambda phone_number, message_text: sent.update(text=message_text) or {'success': True})
        ConversationService.handle_location_check_in('+27821234567', *where)
        return sent.get('text', ''), attempts
    return _share


# ── WhatsApp check-in cases ──────────────────────────────────────────────

def test_first_share_outside_radius_is_checked_in_unverified_with_distance(share):
    store = Store(_session())
    text, attempts = share(store, FAR)
    assert store.doc['status'] == 'checked_in'            # not 'missed'
    ci = store.doc['coach_check_ins']['coach-1']
    assert ci['location_verified'] is False
    assert 1000 < ci['distance'] < 1300
    assert store.doc['location_verified'] is False
    assert "within 100m" in text and "move closer" in text and "share your location again" in text
    assert attempts and attempts[0]['verified'] is False   # attempt record kept


def test_retry_inside_radius_becomes_verified_and_stays_checked_in(share):
    store = Store(_session(check_in={'location_verified': False, 'distance': 1100}, status='checked_in'))
    text, attempts = share(store, AT_VENUE)
    assert store.doc['status'] == 'checked_in'
    ci = store.doc['coach_check_ins']['coach-1']
    assert ci['location_verified'] is True and ci['distance'] < 100
    assert "Checked in" in text
    assert attempts[0]['verified'] is True


def test_retry_still_outside_updates_distance_and_stays_checked_in_unverified(share):
    store = Store(_session(check_in={'location_verified': False, 'distance': 1100}, status='checked_in'))
    text, attempts = share(store, FARTHER)
    assert store.doc['status'] == 'checked_in'
    ci = store.doc['coach_check_ins']['coach-1']
    assert ci['location_verified'] is False
    assert 2000 < ci['distance'] < 2500                    # updated from 1100
    assert "move closer" in text
    assert attempts[0]['verified'] is False


def test_verified_checkin_is_left_alone(share):
    store = Store(_session(check_in={'location_verified': True, 'distance': 12}, status='checked_in'))
    text, attempts = share(store, FAR)
    assert store.writes == [] and attempts == []
    assert "already checked in" in text


def test_session_with_no_venue_is_unchanged_checked_in_unverified(share):
    store = Store(_session(location_id=None))
    text, attempts = share(store, AT_VENUE)
    assert store.doc['status'] == 'checked_in'
    assert store.doc['coach_check_ins']['coach-1']['location_verified'] is False
    assert "GPS not configured" in text
    assert attempts[0]['distance'] is None


def test_multi_coach_session_still_checked_in(share):
    s = _session()
    s['coach_ids'] = ['coach-1', 'coach-2']
    store = Store(s)
    share(store, FAR)
    assert store.doc['status'] == 'checked_in'


# ── the reminder's web check-in link route is unchanged ──────────────────

def test_default_check_in_session_outside_radius_still_sets_missed(monkeypatch):
    """The web link calls check_in_session without the WhatsApp flag: still
    'missed' when outside the radius. The two routes deliberately differ."""
    store = Store(_session())
    monkeypatch.setattr(FirebaseService, 'get_session', lambda sid, org_id: store.get())
    monkeypatch.setattr(FirebaseService, 'get_db', classmethod(lambda cls: _Db(store)))
    FirebaseService.check_in_session('sess-1', {'location': {'latitude': 1, 'longitude': 2},
                                                'location_verified': False, 'distance': 1100},
                                     org_id='org-a', coach_id='coach-1')
    assert store.doc['status'] == 'missed'


# ── the missed-marking sweep never overrides a recorded check-in ─────────

class _TxSnap:
    def __init__(self, data): self._d = data; self.exists = data is not None
    def to_dict(self): return dict(self._d)


class _TxRef:
    def __init__(self, store): self.store = store
    def get(self, transaction=None): return _TxSnap(self.store.doc)


class _TxDb:
    def __init__(self, store): self.store = store
    def collection(self, name): return self
    def document(self, doc_id): return _TxRef(self.store)
    def transaction(self): return _Tx(self.store)


class _Tx:
    def __init__(self, store): self.store = store
    def update(self, ref, data): ref.store.update(data)


@pytest.fixture
def atomic(monkeypatch):
    monkeypatch.setattr(fb_mod.firestore, 'transactional', lambda f: (lambda tx: f(tx)))
    def install(store):
        monkeypatch.setattr(FirebaseService, 'get_db', classmethod(lambda cls: _TxDb(store)))
    return install


@pytest.mark.parametrize('verified', [True, False])
def test_atomic_helper_rescues_any_recorded_check_in_whatever_its_verified_value(atomic, verified):
    store = Store(_session(check_in={'location_verified': verified}, status='reminded'))
    atomic(store)
    assert FirebaseService.mark_session_missed_if_unchecked('sess-1', {'status': 'missed'}) == 'rescued'
    assert store.doc['status'] == 'checked_in'


def test_atomic_helper_does_not_overwrite_a_check_in_that_landed_after_the_snapshot(atomic):
    # the sweep read the session with no check-in; by the time it writes, one exists
    store = Store(_session(status='reminded'))
    store.doc['check_in_time'] = 'now'
    atomic(store)
    assert FirebaseService.mark_session_missed_if_unchecked('sess-1', {'status': 'missed'}) == 'rescued'
    assert store.doc['status'] == 'checked_in'


def test_atomic_helper_marks_missed_only_when_nothing_recorded(atomic):
    store = Store(_session(status='reminded'))
    atomic(store)
    assert FirebaseService.mark_session_missed_if_unchecked('sess-1', {'status': 'missed', 'x': 1}) == 'missed'
    assert store.doc['status'] == 'missed' and store.doc['x'] == 1


def test_atomic_helper_skips_a_session_no_longer_reminded(atomic):
    store = Store(_session(status='checked_in'))
    atomic(store)
    assert FirebaseService.mark_session_missed_if_unchecked('sess-1', {'status': 'missed'}) == 'skipped'
    assert store.doc['status'] == 'checked_in'


@pytest.mark.parametrize('verified', [True, False])
def test_sweep_never_marks_a_session_with_a_check_in_missed(monkeypatch, verified):
    end = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
    sess = {'id': 'sess-1', 'status': 'reminded', 'date': end.strftime('%Y-%m-%d'),
            'start_time': (end - timedelta(hours=1)).strftime('%H:%M'), 'end_time': end.strftime('%H:%M'),
            'coach_check_ins': {'coach-1': {'location_verified': verified, 'distance': 1100}}}

    class _D:
        id = 'sess-1'
        def to_dict(self): return {k: v for k, v in sess.items() if k != 'id'}

    class _Q:
        def where(self, *a, **k): return self
        def stream(self): return iter([_D()])

    class _DbQ:
        def collection(self, name): return _Q()

    monkeypatch.setattr(FirebaseService, 'get_db', classmethod(lambda cls: _DbQ()))
    writes = []
    monkeypatch.setattr(FirebaseService, 'update_session', lambda sid, data: writes.append(data))
    monkeypatch.setattr(FirebaseService, 'mark_session_missed_if_unchecked',
                        lambda sid, data: writes.append(data) or 'missed')
    SchedulerService.mark_missed_sessions()
    assert writes == [{'status': 'checked_in'}]
