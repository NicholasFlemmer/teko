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
from services.person_service import PersonService  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_person_cache():
    """PersonService caches phone -> record lookups for 300s. Reset before
    and after every test so one test's fixture data can never leak into the
    next via a warm cache."""
    PersonService._coach_cache = {}
    PersonService._participant_cache = {}
    PersonService._cache_ts = 0
    yield
    PersonService._coach_cache = {}
    PersonService._participant_cache = {}
    PersonService._cache_ts = 0


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
