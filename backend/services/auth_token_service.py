"""Shared single-use auth token helper for password reset and invite
tokens. Modelled on the check-in token pattern (create_check_in_token /
get_check_in_token / mark_token_used in firebase_service.py, consumed in
routes/sessions.py), with three deliberate differences justified by what
these tokens grant versus what a check-in token grants -- account access,
not a single session's attendance link.

Collection: `auth_tokens`, not `check_in_tokens`. check_in_tokens is
semantically tied to session check-in -- it carries session_id and its
own org-scoping reasoning (deliberately unscoped, since the token itself
is the authorization for an unauthenticated coach). Reset and invite
tokens are a different authorization concept entirely (they grant
account access, not a session action); conflating the two in one
collection is exactly how the next person reuses check-in's org-scoping
assumptions somewhere they don't apply, or vice versa. `auth_tokens`
holds both password-reset and invite tokens, distinguished by a
`token_type` field, rather than a third collection per token type --
the two share every other property (single-use, expiring, looked up by
hash) and a route only ever needs one collection to query.

Token generation: secrets.token_urlsafe(32), not uuid.uuid4(). A
check-in token is a per-session link; these grant account access and are
a far more attractive target, so they get 256 bits from a CSPRNG instead
of a UUID4's ~122.

Storage: the document ID is a SHA-256 hex digest of the raw token, never
the raw token itself -- deliberately NOT hashed the same way passwords
are (werkzeug's pbkdf2/scrypt, salted and slow). That is not an
oversight: those two hashing problems are opposites. A password is a
low-entropy, human-chosen secret, so the slow, salted hash is what makes
offline brute-forcing infeasible -- the algorithm's cost is the whole
point. A token from secrets.token_urlsafe(32) is already 256 bits of
CSPRNG output; slow-hashing it adds cost without adding security margin,
and a salted hash can't be looked up by equality at all (same input
produces a different hash every call), which would force either storing
the salt and re-verifying against every candidate, or a full-collection
scan on every consume() call -- a self-inflicted DoS surface on top of
being slower. A fast, deterministic hash of a high-entropy token lets
consume_auth_token() do a single get-by-ID, exactly the same technique
services/rate_limiter.py already uses to turn an arbitrary key into a
safe Firestore document ID. The raw token itself is returned to the
caller exactly once, by create_auth_token(), for putting in an email --
and is never written to Firestore, logged, or included in any raised
exception's message anywhere in this module.

Timezone handling: timezone-AWARE UTC everywhere, one convention, one
place -- not sessions.py's "add UTC if naive" and uploads.py's "strip
tzinfo if aware" both existing at once. All comparisons go through
_ensure_utc(), so a value that somehow comes back naive is normalized
the same way instead of each caller inventing its own fix.

Concurrency: consume_auth_token() runs its exists/expired/used/type
checks AND the used=True write inside one Firestore transaction (see
services/rate_limiter.py for the same pattern and the same reasoning for
raising max_attempts on a hot document) -- not read-then-write. This is
also where single-use is enforced, once, centrally: the check-in flow
checks `used` at two of its three consumption points and explicitly
allows the third to proceed after use (see sessions.py/uploads.py), and
that inconsistency is exactly what this file exists to not repeat --
every caller of consume_auth_token() gets single-use enforcement
whether it remembers to check for it or not.
"""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from firebase_admin import firestore

from services.firebase_service import FirebaseService

logger = logging.getLogger(__name__)

COLLECTION = 'auth_tokens'

# Fields consume_auth_token()/create_auth_token() own outright. Applied
# after any caller-supplied extra_fields, so a caller can never overwrite
# them (accidentally or otherwise) by passing a colliding key.
_RESERVED_FIELDS = {'token_type', 'subject', 'created_at', 'expires_at', 'used'}


class AuthTokenError(Exception):
    """Base class for every consume_auth_token() failure reason."""


class TokenNotFound(AuthTokenError):
    pass


class TokenExpired(AuthTokenError):
    pass


class TokenAlreadyUsed(AuthTokenError):
    pass


class TokenTypeMismatch(AuthTokenError):
    pass


def _hash_token(raw_token):
    return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()


def _ensure_utc(dt):
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def create_auth_token(token_type, admin_id_or_email, expires_in_minutes, extra_fields=None):
    """Create a new single-use token and return the RAW token.

    The raw token is returned to the caller exactly once, for embedding
    in an email -- it is never stored. Only its hash is written.
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    now = datetime.now(timezone.utc)

    data = dict(extra_fields) if extra_fields else {}
    data.update({
        'token_type': token_type,
        'subject': admin_id_or_email,
        'created_at': firestore.SERVER_TIMESTAMP,
        'expires_at': now + timedelta(minutes=expires_in_minutes),
        'used': False,
    })

    db = FirebaseService.get_db()
    db.collection(COLLECTION).document(token_hash).set(data)

    return raw_token


def consume_auth_token(raw_token, expected_type):
    """Validate and single-use-consume a token in one atomic step.

    Checks, in order: exists, not expired, not already used, correct
    type. Raises TokenNotFound / TokenExpired / TokenAlreadyUsed /
    TokenTypeMismatch on failure -- never raises for "not raised" reasons
    (a Firestore-layer error propagates as whatever exception the client
    itself raises; this function does not swallow those).

    Returns the token record (dict, with 'used' now True) on success.
    """
    db = FirebaseService.get_db()
    doc_ref = db.collection(COLLECTION).document(_hash_token(raw_token))
    # max_attempts higher than the client's default (5): same reasoning
    # as services/rate_limiter.py -- a token that's the target of a
    # double-submit (e.g. a user double-clicking a reset link, or two
    # concurrent requests racing the same token) is a hot-document case
    # by construction, not an edge case.
    transaction = db.transaction(max_attempts=15)
    return _consume(transaction, doc_ref, expected_type)


@firestore.transactional
def _consume(transaction, doc_ref, expected_type):
    snapshot = doc_ref.get(transaction=transaction)
    if not snapshot.exists:
        raise TokenNotFound("no auth token matches the value supplied")

    record = snapshot.to_dict()

    expires_at = record.get('expires_at')
    if expires_at is None or datetime.now(timezone.utc) > _ensure_utc(expires_at):
        raise TokenExpired("this token has expired")

    if record.get('used'):
        raise TokenAlreadyUsed("this token has already been used")

    if record.get('token_type') != expected_type:
        raise TokenTypeMismatch(
            f"expected a {expected_type!r} token, got {record.get('token_type')!r}"
        )

    transaction.update(doc_ref, {
        'used': True,
        'used_at': firestore.SERVER_TIMESTAMP,
    })

    record['used'] = True
    return record
