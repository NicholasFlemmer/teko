"""Tests for services/auth_token_service.py.

Like test_rate_limiter.py, these talk to REAL staging Firestore rather
than a mock -- the whole point of this module is atomic single-use
consumption under a Firestore transaction, and a mocked transaction can't
faithfully prove "two concurrent consumptions of the same token yield
exactly one success." Every token created here is tracked and its
document deleted in a teardown fixture, so this never leaves permanent
documents behind in `auth_tokens`.

Refuses to run against anything other than teko-staging-tgh -- enforced
by tests/conftest.py, which runs before any test module in this
directory is imported.

Usage:
    cd backend
    pytest tests/test_auth_token_service.py -v
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

from services import auth_token_service  # noqa: E402
from services.auth_token_service import (  # noqa: E402
    create_auth_token,
    consume_auth_token,
    _hash_token,
    TokenNotFound,
    TokenExpired,
    TokenAlreadyUsed,
    TokenTypeMismatch,
)
from services.firebase_service import FirebaseService  # noqa: E402

RUN_TOKEN = uuid.uuid4().hex[:12]
SUBJECT = f'test-{RUN_TOKEN}@example.com'
_created_hashes = []


def _tracked_token(token_type='password_reset', expires_in_minutes=60, extra_fields=None):
    raw = create_auth_token(token_type, SUBJECT, expires_in_minutes, extra_fields=extra_fields)
    _created_hashes.append(_hash_token(raw))
    return raw


@pytest.fixture(autouse=True, scope='module')
def _cleanup_test_docs():
    yield
    db = FirebaseService.get_db()
    for token_hash in _created_hashes:
        db.collection(auth_token_service.COLLECTION).document(token_hash).delete()


def _doc(raw_token):
    db = FirebaseService.get_db()
    return db.collection(auth_token_service.COLLECTION).document(_hash_token(raw_token)).get()


def test_valid_token_consumes_once_and_fails_the_second_time():
    raw = _tracked_token()

    record = consume_auth_token(raw, expected_type='password_reset')
    assert record['used'] is True
    assert record['subject'] == SUBJECT

    with pytest.raises(TokenAlreadyUsed):
        consume_auth_token(raw, expected_type='password_reset')


def test_expired_token_is_rejected():
    raw = _tracked_token()
    # Force expiry directly, same technique test_rate_limiter.py uses for
    # its window-reset test, rather than a real sleep.
    doc_ref = FirebaseService.get_db().collection(auth_token_service.COLLECTION).document(_hash_token(raw))
    doc_ref.update({'expires_at': datetime.now(timezone.utc) - timedelta(minutes=1)})

    with pytest.raises(TokenExpired):
        consume_auth_token(raw, expected_type='password_reset')


def test_wrong_type_is_rejected():
    raw = _tracked_token(token_type='invite')
    with pytest.raises(TokenTypeMismatch):
        consume_auth_token(raw, expected_type='password_reset')


def test_unknown_token_is_rejected():
    never_issued = 'never-issued-' + uuid.uuid4().hex
    with pytest.raises(TokenNotFound):
        consume_auth_token(never_issued, expected_type='password_reset')


def test_raw_token_never_appears_in_the_stored_document():
    raw = _tracked_token(extra_fields={'org_id': 'some-org', 'role': 'location_admin'})
    stored = _doc(raw).to_dict()

    assert stored is not None
    for field_name, value in stored.items():
        assert raw not in str(value), f"raw token leaked into field {field_name!r}"
    # No field storing the plaintext token under any name either.
    assert all(k not in ('token', 'raw_token', 'value') for k in stored.keys())


def test_concurrent_consumption_of_the_same_token_yields_exactly_one_success():
    raw = _tracked_token()

    def _attempt(_):
        try:
            consume_auth_token(raw, expected_type='password_reset')
            return 'success'
        except TokenAlreadyUsed:
            return 'already_used'

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_attempt, range(8)))

    assert results.count('success') == 1, results
    assert results.count('already_used') == 7, results
