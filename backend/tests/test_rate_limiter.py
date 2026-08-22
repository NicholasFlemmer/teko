"""Tests for services/rate_limiter.py.

Unlike most of this suite, these tests deliberately talk to REAL staging
Firestore rather than a mock. rate_limiter.py's entire job is atomic
behaviour under a Firestore transaction -- a mock of db.transaction()
can't faithfully prove "two concurrent requests can't both win", only a
real transaction can. Every key used here is prefixed with a random
per-test-run token and cleaned up in a fixture teardown, so this never
leaves permanent documents behind in the `rate_limits` collection --
consistent with the "must not grow forever" requirement the module
itself was built to satisfy.

Refuses to run against anything other than teko-staging-tgh -- enforced
by tests/conftest.py, which runs before any test module in this
directory is imported.

Usage:
    cd backend
    pytest tests/test_rate_limiter.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) now lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

import uuid  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402

from services import rate_limiter  # noqa: E402
from services.rate_limiter import is_rate_limited  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402

RUN_TOKEN = uuid.uuid4().hex[:12]
_created_keys = []


def _fresh_key(label):
    key = f"test:{RUN_TOKEN}:{label}:{uuid.uuid4().hex[:8]}"
    _created_keys.append(key)
    return key


@pytest.fixture(autouse=True, scope='module')
def _cleanup_test_docs():
    yield
    db = FirebaseService.get_db()
    for key in _created_keys:
        db.collection(rate_limiter.COLLECTION).document(rate_limiter._doc_id(key)).delete()


def _read_stored_count(key):
    db = FirebaseService.get_db()
    snapshot = db.collection(rate_limiter.COLLECTION).document(rate_limiter._doc_id(key)).get()
    assert snapshot.exists, f"expected a rate_limits doc for key {key!r}, found none"
    return snapshot.to_dict()['count']


def test_under_limit_passes_through():
    key = _fresh_key('under')
    for _ in range(3):
        assert is_rate_limited(key, max_count=3, window_seconds=60) is False


def test_over_limit_returns_true():
    key = _fresh_key('over')
    for _ in range(3):
        assert is_rate_limited(key, max_count=3, window_seconds=60) is False
    assert is_rate_limited(key, max_count=3, window_seconds=60) is True
    # Still over limit on a subsequent attempt too, not a one-shot flip.
    assert is_rate_limited(key, max_count=3, window_seconds=60) is True


def test_window_resets():
    key = _fresh_key('reset')
    for _ in range(3):
        is_rate_limited(key, max_count=3, window_seconds=60)
    assert is_rate_limited(key, max_count=3, window_seconds=60) is True

    # Simulate the window having elapsed by writing window_start directly
    # into the past, rather than a real sleep -- exercises the exact same
    # "window_expired" branch a real 60s wait would, without the test
    # taking 60s.
    db = FirebaseService.get_db()
    doc_ref = db.collection(rate_limiter.COLLECTION).document(rate_limiter._doc_id(key))
    doc_ref.update({'window_start': datetime.now(timezone.utc) - timedelta(seconds=120)})

    assert is_rate_limited(key, max_count=3, window_seconds=60) is False
    assert _read_stored_count(key) == 1  # reset in place, not accumulated


def test_counter_is_shared_not_per_process():
    """Proves the count lives in Firestore, not in any Python-side state
    in the rate_limiter module -- reads the document back independently
    of is_rate_limited() itself and checks it agrees."""
    key = _fresh_key('shared')
    for _ in range(4):
        is_rate_limited(key, max_count=100, window_seconds=60)
    assert _read_stored_count(key) == 4


def test_concurrent_requests_do_not_lose_updates():
    """Fires 8 truly concurrent requests at the same key and asserts the
    final stored count is exactly 8 -- proves the transaction prevents the
    classic read-then-write race (two requests both reading count=N and
    both writing N+1, which would under-count).

    8 workers, not more: this is a same-document write-contention test,
    and Firestore's default transaction retry (5 attempts, exponential
    backoff) is tuned for realistic contention on a single login/IP key,
    not for absorbing dozens of literally simultaneous transactions on
    one document -- that's a different problem (hot-document sharding),
    not something this endpoint's real traffic pattern needs. Pushing
    this higher (tried 20) demonstrates the OTHER deliberate behaviour
    instead: a transaction that can't commit after retrying fails closed
    (returns True, records nothing) rather than risking a lost update --
    which is correct, but means "no lost updates" and "every attempt gets
    counted" aren't the same guarantee under contention this extreme.
    """
    key = _fresh_key('concurrent')
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: is_rate_limited(key, max_count=1000, window_seconds=60), range(8)))
    assert _read_stored_count(key) == 8


def test_fails_closed_when_firestore_unreachable(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("simulated Firestore outage")

    monkeypatch.setattr(FirebaseService, 'get_db', classmethod(lambda cls: (_ for _ in ()).throw(RuntimeError("boom"))))

    # Must not raise -- must fail closed (over limit) instead.
    assert is_rate_limited(_fresh_key('unreachable'), max_count=1000, window_seconds=60) is True
