import logging
import time

from services.firebase_service import FirebaseService
from utils.phone import mask_phone, normalize_phone_for_matching

logger = logging.getLogger(__name__)


class PersonCacheUnavailableError(Exception):
    """Raised by resolve() when the person cache has never successfully
    populated and the current refresh attempt has also failed.

    This is deliberately NOT the same outcome as resolve() returning None
    (which means "the cache is healthy, this phone matches nobody"). If a
    cache that has never loaded were treated as "no match", a real,
    already-registered coach or participant would be told they aren't
    registered — the exact failure mode this exception exists to prevent.
    Callers must catch this and reply with a transient-error message
    instead of the unregistered-sender message.
    """
    pass


class PersonService:
    """Resolves an incoming WhatsApp phone number to the person it belongs
    to, across both the coaches and participants collections.

    This is identity resolution only — deciding WHO sent a message. Nothing
    downstream of resolve() is touched by this service: command routing,
    the persona prompt, RAG context, broadcasts, reports, and the scheduler
    still work exactly as they did before PersonService existed.
    """

    # In-memory cache: normalised phone -> record dict, one cache per
    # collection. Rebuilt every 5 minutes. This is now the ONLY phone -> person
    # identity cache in the codebase — ConversationService used to keep its
    # own duplicate coach-only cache (_coach_phone_cache/get_coach_by_phone),
    # removed in Phase 2 step 3c once this one covered its one remaining
    # caller, to avoid two caches drifting out of sync.
    #
    # DELIBERATE EXCEPTION to Phase 0 org scoping: both scans span every
    # org, because the org isn't known until AFTER the phone resolves to a
    # person (analogous to login-by-email). Every other Firestore accessor
    # in this codebase requires org_id; this is the one accepted exception.
    _coach_cache: dict = {}
    _participant_cache: dict = {}
    # normalised phone -> list of every colliding coach record (2+ coaches
    # sharing that number, same org or across orgs). A phone in here is
    # deliberately withheld from _coach_cache -- see resolve(): one phone
    # number must belong to exactly one coach, so a collision refuses
    # rather than picking a winner.
    _coach_collisions: dict = {}
    _cache_ts: float = 0
    _CACHE_TTL = 300  # seconds

    # True once a refresh has EVER succeeded. Deliberately independent of
    # whether _coach_cache/_participant_cache are non-empty, so a refresh
    # that legitimately finds zero coaches/participants still counts as
    # "healthy" — the failure mode this guards against is a cache that has
    # never successfully loaded at all, not one that loaded an empty org.
    _cache_populated: bool = False

    @staticmethod
    def _safe_normalize(phone_number):
        """normalize_phone_for_matching(), but a single malformed stored
        phone number (None, empty, garbage) can never raise and break
        resolution for every other record in the same refresh.

        Uses normalize_phone_for_matching(), NOT normalize_sa_phone()
        directly: the latter rejects anything that isn't SA-shaped, which
        would make identity resolution SA-only — a real regression (e.g.
        a Brazilian coach's number would never resolve). The matching
        variant falls back to a permissive strip-only normalization for
        non-SA numbers instead of rejecting them.
        """
        try:
            return normalize_phone_for_matching(phone_number) or ''
        except Exception:
            return ''

    @staticmethod
    def _log_duplicate_phone(collection_label, normalised, existing_record, new_record):
        """Log a normalised phone number about to overwrite an existing
        cache entry. Detection only -- the caller still overwrites
        unconditionally afterward, so last-write-wins is unchanged.

        PARTICIPANT-ONLY as of the coach fail-closed change below: coach
        collisions no longer overwrite, they refuse (see
        _log_coach_phone_collision / resolve()). This method still governs
        participant duplicates, which are out of scope for that change.

        Different org_id: ERROR. This is the cross-org routing hazard —
        the record being overwritten will never resolve for its own org
        again once this refresh completes.

        Same org_id: WARNING. Two records for the same person/number
        inside one org is a data quality issue, not a routing hazard.
        """
        existing_org = existing_record.get('org_id')
        new_org = new_record.get('org_id')
        if existing_org != new_org:
            logger.error(
                "Duplicate %s phone number %s across orgs %s and %s — "
                "the org_id=%s record will win in the identity cache; the "
                "org_id=%s record will never resolve for its own org until "
                "this is fixed.",
                collection_label, mask_phone(normalised), existing_org, new_org,
                new_org, existing_org,
            )
        else:
            logger.warning(
                "Duplicate %s phone number %s within org %s — two records "
                "share the same phone number. Data quality issue, not a "
                "cross-org routing hazard.",
                collection_label, mask_phone(normalised), existing_org,
            )

    @staticmethod
    def _log_coach_phone_collision(normalised, records):
        """Log an ERROR naming every coach record colliding on this
        normalised phone number, at the moment resolve() actually refuses
        to serve it.

        Two or more coach records must never share a phone number --
        whether they're in the same org (a data-quality duplicate) or
        different orgs (the cross-org routing hazard the shared identity
        cache used to paper over by silently picking a winner). Either
        way, one phone number must belong to exactly one coach; resolve()
        refuses rather than guessing, and this is the only place that
        refusal gets logged, with enough detail (every colliding coach_id
        and org_id) to diagnose and fix the duplicate from logs alone.
        """
        org_ids = {r.get('org_id') for r in records}
        kind = 'cross-org' if len(org_ids) > 1 else 'same-org'
        detail = ', '.join(
            f"coach_id={r.get('id')!r} org_id={r.get('org_id')!r}" for r in records
        )
        logger.error(
            "Refusing to resolve coach phone number %s — %s collision across "
            "%d coach records: %s. One phone number must belong to exactly "
            "one coach in exactly one org; fix the duplicate before this "
            "number can resolve again.",
            mask_phone(normalised), kind, len(records), detail,
        )

    @classmethod
    def _refresh_cache_if_stale(cls):
        """Refresh the cache if it's stale (or has never populated).

        On failure, the existing cache — stale or not — is left exactly as
        it was: a failed refresh must never wipe out the last known good
        data. Only ERROR-logging happens here; resolve() is what decides
        whether a failure is safe to serve through (stale-but-populated)
        or must be surfaced as unavailable (never-populated).
        """
        now = time.time()
        if now - cls._cache_ts < cls._CACHE_TTL and cls._cache_populated:
            return
        try:
            coaches = FirebaseService.get_all_coaches(None)
            participants = FirebaseService.get_all_participants(None)

            # Group every coach by normalised phone first, rather than
            # overwriting a dict entry as we go -- overwriting is what let
            # a collision silently pick a winner before. A phone with 2+
            # coach records is withheld from coach_cache entirely and
            # recorded in coach_collisions instead; resolve() refuses those
            # rather than serving one of the colliding records.
            coach_phone_groups: dict = {}
            for coach in coaches:
                normalised = cls._safe_normalize(coach.get('phone_number', ''))
                if normalised:
                    coach_phone_groups.setdefault(normalised, []).append(coach)

            coach_cache = {}
            coach_collisions = {}
            for normalised, records in coach_phone_groups.items():
                if len(records) > 1:
                    coach_collisions[normalised] = records
                else:
                    coach_cache[normalised] = records[0]

            participant_cache = {}
            for participant in participants:
                normalised = cls._safe_normalize(participant.get('phone_number', ''))
                if normalised:
                    existing = participant_cache.get(normalised)
                    if existing:
                        cls._log_duplicate_phone('participant', normalised, existing, participant)
                    participant_cache[normalised] = participant

            cls._coach_cache = coach_cache
            cls._coach_collisions = coach_collisions
            cls._participant_cache = participant_cache
            cls._cache_ts = now
            cls._cache_populated = True
        except Exception as e:
            if cls._cache_populated:
                logger.error(
                    "Error refreshing person cache — serving last known good "
                    "(stale) cache from %.0fs ago instead: %s",
                    now - cls._cache_ts, e,
                )
            else:
                logger.error(
                    "Error refreshing person cache — cache has NEVER "
                    "successfully populated, identity resolution is "
                    "currently unavailable: %s", e,
                )

    @classmethod
    def resolve(cls, phone):
        """Resolve `phone` to a Person dict, or None if nobody matches.

        A Person dict is the underlying coach/participant record (id,
        org_id, name, phone_number, plus whatever other fields that record
        has) with an added 'person_type' key: 'coach' or 'participant'.

        Both sides of the comparison are normalised via
        normalize_phone_for_matching() at lookup time — never assume stored
        numbers are already canonical. Some existing coach records were
        saved through paths that predate normalize_sa_phone(), so comparing
        raw strings would silently stop matching them; normalizing both
        sides can only ever increase the match rate, never decrease it.
        normalize_phone_for_matching() (not normalize_sa_phone() directly)
        is what makes this work for non-SA numbers too — normalize_sa_phone()
        alone would reject them outright rather than widen the match.

        Resolution order: coaches first, then participants. If a phone
        somehow matches both, that's a data problem someone needs to see —
        this logs a warning and returns the coach rather than silently
        picking a winner.

        If a normalised phone number matches MORE THAN ONE coach record —
        whether those coaches are in the same org or different orgs — this
        refuses to resolve it at all: it does not pick the first, the
        last, or the most recent. One phone number must belong to exactly
        one coach. The refusal is logged as an ERROR naming every
        colliding coach_id and org_id (see _log_coach_phone_collision) so
        the duplicate is diagnosable from logs, then this behaves exactly
        like "no coach matches" for that phone (participants are still
        checked normally).

        Raises PersonCacheUnavailableError if the cache has never
        successfully populated (see _refresh_cache_if_stale) — this must
        stay distinguishable from returning None. A stale-but-previously
        -healthy cache is served through as normal (a phone missing from it
        is a normal "not registered" result); only a cache that has NEVER
        loaded means we have no signal at all, which is a different failure
        that callers must not present as "you aren't registered".
        """
        normalised = cls._safe_normalize(phone)
        if not normalised:
            return None

        cls._refresh_cache_if_stale()

        if not cls._cache_populated:
            raise PersonCacheUnavailableError(
                "Person cache has never successfully populated; cannot "
                "resolve phone numbers right now."
            )

        colliding_coaches = cls._coach_collisions.get(normalised)
        if colliding_coaches:
            cls._log_coach_phone_collision(normalised, colliding_coaches)
            coach = None
        else:
            coach = cls._coach_cache.get(normalised)

        participant = cls._participant_cache.get(normalised)

        if coach and participant:
            logger.warning(
                "Phone %s matches both a coach (id=%s) and a participant "
                "(id=%s) — this is a data problem, returning the coach. "
                "Investigate the duplicate phone_number value across the "
                "coaches and participants collections.",
                mask_phone(normalised), coach.get('id'), participant.get('id'),
            )
            return {**coach, 'person_type': 'coach'}

        if coach:
            return {**coach, 'person_type': 'coach'}

        if participant:
            return {**participant, 'person_type': 'participant'}

        return None

    @classmethod
    def get_colliding_org_ids(cls, phone):
        """Return the distinct org_ids of every coach record colliding on
        this phone number, or [] if it isn't a known collision.

        Exists for callers that must act on a collision even though
        resolve() itself refuses to name a person for it — currently
        safeguarding alerting (see ConversationService), which must
        still reach every colliding org's safeguarding lead without
        knowing (or guessing) which one actually sent the message.

        Read-only: refreshes the cache the same way resolve() does, but
        never raises PersonCacheUnavailableError — a cache that has
        never populated simply means no collision is known yet, so this
        returns [] rather than surfacing that as an error. Callers that
        need to distinguish "cache unavailable" from "no collision" must
        use resolve() directly.
        """
        normalised = cls._safe_normalize(phone)
        if not normalised:
            return []

        cls._refresh_cache_if_stale()
        if not cls._cache_populated:
            return []

        records = cls._coach_collisions.get(normalised)
        if not records:
            return []
        return sorted({r.get('org_id') for r in records if r.get('org_id')})
