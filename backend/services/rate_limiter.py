"""Firestore-backed rate limiting, shared across Cloud Run instances.

Deliberately not Flask-Limiter's default in-memory storage: the backend
runs on Cloud Run with multiple instances, so an in-process counter is
per-instance and the limit stops meaning anything once traffic is spread
across more than one instance. This stores one counter document per key
in the `rate_limits` collection instead, so every instance reads and
writes the same counter.

Design: one document per key, reset in place (not one document per key
per window). A key's window is tracked by a `window_start` field on that
single document; when a check finds the current window has elapsed, the
transaction resets count=1 and window_start=now on the SAME document
rather than writing a new one. This means the number of documents in
`rate_limits` is bounded by the number of distinct keys ever rate-limited
(distinct emails/IPs), not by the number of windows that have ever
elapsed for them -- so nothing accumulates over time the way "one new
document per key per window, forever" would. No Firestore TTL policy or
cleanup job is required for this to stay bounded.

Concurrency: the read-check-write inside check_and_increment() runs
inside a Firestore transaction (@firestore.transactional), not a plain
read-then-write -- Firestore retries the transaction automatically on
contention, so two concurrent requests against the same key can't both
read count=4, both decide "under the limit", and both write count=5.

Failure mode (deliberate): if the Firestore transaction itself raises
(the collection is unreachable, quota, etc.), is_rate_limited() fails
CLOSED -- it returns True (over limit) rather than allowing the request
through. This matches the existing convention in this codebase of
failing closed on a Firestore error rather than falling through to a
permissive default (see routes/auth.py login()'s own "Fail closed --
don't fall through to env-var credentials on Firestore errors"). The
alternative -- fail open -- would mean any transient Firestore blip (or
anything that could deliberately provoke one) hands an attacker an
unlimited-attempts window on exactly the endpoint this exists to
protect. login() already 503s on a Firestore error in the admin lookup
itself, so failing closed here does not introduce a new class of outage
-- it's consistent with a path that already fails closed one step later.
"""
import hashlib
import logging
from datetime import datetime, timedelta, timezone

from firebase_admin import firestore

from services.firebase_service import FirebaseService

logger = logging.getLogger(__name__)

COLLECTION = 'rate_limits'


def _doc_id(key):
    # Hash rather than use the raw key as the doc ID: keeps doc IDs a
    # fixed, safe shape regardless of what's in `key` (an email may
    # contain characters that are legal in a Firestore doc ID but are
    # still worth not depending on), and keeps the raw email/IP out of
    # anything logged as a doc ID. The raw key is still stored as a
    # field on the document itself, for operational visibility.
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


def is_rate_limited(key, max_count, window_seconds):
    """Record one attempt for `key` and report whether it's over the limit.

    Returns True if `key` has now made more than `max_count` attempts
    within the trailing `window_seconds`-second window, False otherwise.
    Never raises -- see module docstring for the deliberate fail-closed
    behaviour if Firestore itself is unreachable.
    """
    try:
        db = FirebaseService.get_db()
        if db is None:
            logger.error("[rate_limiter] No Firestore client available — failing closed for key.")
            return True

        doc_ref = db.collection(COLLECTION).document(_doc_id(key))
        # max_attempts higher than the client's default (5): a rate limiter
        # is, by definition, a hot-document use case -- multiple requests
        # racing the same key is the normal case this exists to handle
        # correctly, not an edge case, so it needs more retry headroom than
        # Firestore's general-purpose default gives it.
        transaction = db.transaction(max_attempts=15)
        return _check_and_increment(transaction, doc_ref, key, max_count, window_seconds)
    except Exception:
        logger.exception("[rate_limiter] Firestore error checking rate limit — failing closed.")
        return True


@firestore.transactional
def _check_and_increment(transaction, doc_ref, key, max_count, window_seconds):
    snapshot = doc_ref.get(transaction=transaction)
    now = datetime.now(timezone.utc)

    window_start = None
    count = 0
    if snapshot.exists:
        window_start = snapshot.get('window_start')
        count = snapshot.get('count') or 0

    window_expired = (
        window_start is None
        or now - window_start >= timedelta(seconds=window_seconds)
    )

    if window_expired:
        new_count = 1
        new_window_start = now
    else:
        new_count = count + 1
        new_window_start = window_start

    transaction.set(doc_ref, {
        'key': key,
        'count': new_count,
        'window_start': new_window_start,
        'window_seconds': window_seconds,
        'updated_at': firestore.SERVER_TIMESTAMP,
    })

    return new_count > max_count
