"""Unit tests for PersonService.resolve — identity resolution only.

Unlike test_org_isolation.py, these are pure unit tests: FirebaseService's
directory reads are stubbed via monkeypatch, so nothing here touches
Firestore. Coach/participant fixtures use realistic South African and
Brazilian-shaped phone formats, exercising both normalize_phone_for_matching()
paths — the SA canonical path and the permissive international fallback.
See test_person_resolution_e2e.py for end-to-end coverage against the real
seeded staging phone numbers via handle_incoming_message directly.

Usage:
    cd backend
    pytest tests/test_person_service.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest  # noqa: E402
from services.person_service import PersonService, PersonCacheUnavailableError  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_person_cache():
    """PersonService caches phone -> record lookups for 300s. Reset before
    and after every test so one test's fixture data can never leak into the
    next via a warm cache."""
    PersonService._coach_cache = {}
    PersonService._participant_cache = {}
    PersonService._cache_ts = 0
    PersonService._cache_populated = False
    yield
    PersonService._coach_cache = {}
    PersonService._participant_cache = {}
    PersonService._cache_ts = 0
    PersonService._cache_populated = False


def _stub_directory(monkeypatch, coaches=None, participants=None):
    monkeypatch.setattr(FirebaseService, 'get_all_coaches', lambda org_id: coaches or [])
    monkeypatch.setattr(FirebaseService, 'get_all_participants', lambda org_id: participants or [])


def test_resolve_matches_coach(monkeypatch):
    _stub_directory(monkeypatch, coaches=[
        {'id': 'coach-1', 'org_id': 'org-a', 'name': 'Alice', 'phone_number': '0821234567'},
    ])

    person = PersonService.resolve('27821234567')

    assert person is not None
    assert person['person_type'] == 'coach'
    assert person['id'] == 'coach-1'
    assert person['org_id'] == 'org-a'
    assert person['name'] == 'Alice'


def test_resolve_matches_participant(monkeypatch):
    _stub_directory(monkeypatch, participants=[
        {'id': 'participant-1', 'org_id': 'org-a', 'name': 'Bob', 'phone_number': '0839876543'},
    ])

    person = PersonService.resolve('27839876543')

    assert person is not None
    assert person['person_type'] == 'participant'
    assert person['id'] == 'participant-1'
    assert person['name'] == 'Bob'


def test_resolve_no_match(monkeypatch):
    _stub_directory(monkeypatch, coaches=[
        {'id': 'coach-1', 'org_id': 'org-a', 'name': 'Alice', 'phone_number': '0821234567'},
    ])

    assert PersonService.resolve('27000000000') is None


def test_resolve_matches_non_canonical_stored_phone(monkeypatch):
    """The stored phone is spaced/dashed/plus-prefixed — not the canonical
    27XXXXXXXXX form normalize_sa_phone() would produce. Proves both sides
    of the comparison are normalised, not just the incoming number."""
    _stub_directory(monkeypatch, coaches=[
        {'id': 'coach-1', 'org_id': 'org-a', 'name': 'Carol', 'phone_number': '+27-82-555-1234'},
    ])

    person = PersonService.resolve('0825551234')

    assert person is not None
    assert person['id'] == 'coach-1'


def test_resolve_both_match_logs_warning_and_returns_coach(monkeypatch, caplog):
    """A phone somehow matching both a coach and a participant is a data
    problem, not something to silently pick a winner on: it must be logged,
    and the coach must win."""
    _stub_directory(
        monkeypatch,
        coaches=[{'id': 'coach-1', 'org_id': 'org-a', 'name': 'Dan', 'phone_number': '0821112222'}],
        participants=[{'id': 'participant-1', 'org_id': 'org-a', 'name': 'Dan Duplicate', 'phone_number': '0821112222'}],
    )

    with caplog.at_level('WARNING'):
        person = PersonService.resolve('27821112222')

    assert person is not None
    assert person['person_type'] == 'coach'
    assert person['id'] == 'coach-1'
    assert any('both' in record.message.lower() for record in caplog.records), (
        "Expected a warning log mentioning the both-match data problem."
    )


def test_resolve_matches_international_coach(monkeypatch):
    """A non-SA number (Brazilian-shaped) must still resolve. Regression
    test: normalize_sa_phone() alone rejects anything not SA-shaped, which
    would make identity resolution SA-only — PersonService must use the
    permissive normalize_phone_for_matching() fallback instead."""
    _stub_directory(monkeypatch, coaches=[
        {'id': 'coach-br', 'org_id': 'org-a', 'name': 'Eduardo', 'phone_number': '+55 11 98765-4321'},
    ])

    person = PersonService.resolve('5511987654321')

    assert person is not None
    assert person['person_type'] == 'coach'
    assert person['id'] == 'coach-br'


def test_resolve_matches_international_participant(monkeypatch):
    """Same regression coverage as above, for a participant."""
    _stub_directory(monkeypatch, participants=[
        {'id': 'participant-br', 'org_id': 'org-a', 'name': 'Fernanda', 'phone_number': '+5511912345678'},
    ])

    person = PersonService.resolve('5511912345678')

    assert person is not None
    assert person['person_type'] == 'participant'
    assert person['id'] == 'participant-br'


def test_resolve_skips_malformed_stored_phone_without_breaking_others(monkeypatch):
    """One record with a None/garbage phone_number must not prevent a
    well-formed record elsewhere in the same directory from resolving."""
    _stub_directory(monkeypatch, coaches=[
        {'id': 'coach-bad', 'org_id': 'org-a', 'name': 'Bad Data', 'phone_number': None},
        {'id': 'coach-good', 'org_id': 'org-a', 'name': 'Good Data', 'phone_number': '0821234567'},
    ])

    person = PersonService.resolve('27821234567')

    assert person is not None
    assert person['id'] == 'coach-good'


# ---------------------------------------------------------------------------
# Phase 2 step 3c: a broken cache refresh must never present as "this phone
# isn't registered" — see PersonService._refresh_cache_if_stale/resolve.
# ---------------------------------------------------------------------------

def _raise(exc):
    return lambda *a, **kw: (_ for _ in ()).throw(exc)


def test_cold_start_refresh_failure_raises_unavailable_not_none(monkeypatch, caplog):
    """The cache has NEVER successfully populated (fresh process, or every
    refresh so far has failed) and this refresh attempt also fails. This
    must raise, not return None — a None here is indistinguishable from
    "cache is healthy, nobody matches", which would tell a real coach or
    participant they aren't registered when the actual problem is a broken
    Firestore read."""
    monkeypatch.setattr(FirebaseService, 'get_all_coaches', _raise(Exception("simulated Firestore outage")))
    monkeypatch.setattr(FirebaseService, 'get_all_participants', _raise(Exception("simulated Firestore outage")))

    with caplog.at_level('ERROR'):
        with pytest.raises(PersonCacheUnavailableError):
            PersonService.resolve('27821234567')

    assert any(r.levelname == 'ERROR' and 'never' in r.message.lower() for r in caplog.records), (
        "Expected an ERROR log distinguishing a never-populated cache from a stale one."
    )


def test_stale_cache_served_through_on_refresh_failure(monkeypatch, caplog):
    """The cache populated successfully once, then TTL expired, then the
    next refresh attempt fails (e.g. a transient Firestore blip). The
    coach who was already in that last-known-good snapshot must still
    resolve normally — a stale-but-populated cache is safe to keep serving,
    it is NOT the same failure as a cache that has never loaded."""
    _stub_directory(monkeypatch, coaches=[
        {'id': 'coach-1', 'org_id': 'org-a', 'name': 'Alice', 'phone_number': '0821234567'},
    ])
    person = PersonService.resolve('27821234567')
    assert person is not None and person['id'] == 'coach-1'

    # Force the cache to look stale, then make the next refresh fail.
    PersonService._cache_ts = 0
    monkeypatch.setattr(FirebaseService, 'get_all_coaches', _raise(Exception("simulated Firestore outage")))
    monkeypatch.setattr(FirebaseService, 'get_all_participants', _raise(Exception("simulated Firestore outage")))

    with caplog.at_level('ERROR'):
        person_again = PersonService.resolve('27821234567')

    assert person_again is not None, "A stale-but-previously-populated cache must still be served on refresh failure."
    assert person_again['id'] == 'coach-1'
    assert any(r.levelname == 'ERROR' and 'stale' in r.message.lower() for r in caplog.records), (
        "Expected an ERROR log noting the stale cache is being served through."
    )


def test_refresh_failure_does_not_wipe_existing_cache_data(monkeypatch):
    """A failed refresh must leave _coach_cache/_participant_cache exactly
    as they were — never reset to empty. Destroying good data on a
    transient failure would be worse than the original silent-empty bug."""
    _stub_directory(monkeypatch, coaches=[
        {'id': 'coach-1', 'org_id': 'org-a', 'name': 'Alice', 'phone_number': '0821234567'},
    ])
    PersonService.resolve('27821234567')
    assert PersonService._coach_cache  # populated

    PersonService._cache_ts = 0
    monkeypatch.setattr(FirebaseService, 'get_all_coaches', _raise(Exception("simulated Firestore outage")))
    monkeypatch.setattr(FirebaseService, 'get_all_participants', _raise(Exception("simulated Firestore outage")))
    PersonService._refresh_cache_if_stale()

    assert PersonService._coach_cache.get('27821234567', {}).get('id') == 'coach-1', (
        "A failed refresh must not discard the last known good cache."
    )


def test_resolve_no_match_with_healthy_cache_still_returns_none(monkeypatch):
    """Regression guard: the normal 'not registered' outcome (cache loaded
    fine, this phone just isn't in it) must still return None, not raise —
    PersonCacheUnavailableError is only for a cache that never populated."""
    _stub_directory(monkeypatch, coaches=[
        {'id': 'coach-1', 'org_id': 'org-a', 'name': 'Alice', 'phone_number': '0821234567'},
    ])

    assert PersonService.resolve('27000000000') is None
