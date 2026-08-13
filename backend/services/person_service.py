import logging
import time

from services.firebase_service import FirebaseService
from utils.phone import normalize_phone_for_matching

logger = logging.getLogger(__name__)


class PersonService:
    """Resolves an incoming WhatsApp phone number to the person it belongs
    to, across both the coaches and participants collections.

    This is identity resolution only — deciding WHO sent a message. Nothing
    downstream of resolve() is touched by this service: command routing,
    the persona prompt, RAG context, broadcasts, reports, and the scheduler
    still work exactly as they did before PersonService existed.
    """

    # In-memory cache: normalised phone -> record dict, one cache per
    # collection. Rebuilt every 5 minutes, mirroring
    # ConversationService._coach_phone_cache (same TTL, same strategy — not
    # changed in this step).
    #
    # DELIBERATE EXCEPTION to Phase 0 org scoping: both scans span every
    # org, because the org isn't known until AFTER the phone resolves to a
    # person (analogous to login-by-email). Every other Firestore accessor
    # in this codebase requires org_id; this is the one accepted exception,
    # matching ConversationService.get_coach_by_phone's existing behaviour.
    _coach_cache: dict = {}
    _participant_cache: dict = {}
    _cache_ts: float = 0
    _CACHE_TTL = 300  # seconds

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

    @classmethod
    def _refresh_cache_if_stale(cls):
        now = time.time()
        if now - cls._cache_ts < cls._CACHE_TTL and (cls._coach_cache or cls._participant_cache):
            return
        try:
            coaches = FirebaseService.get_all_coaches(None)
            participants = FirebaseService.get_all_participants(None)

            coach_cache = {}
            for coach in coaches:
                normalised = cls._safe_normalize(coach.get('phone_number', ''))
                if normalised:
                    coach_cache[normalised] = coach

            participant_cache = {}
            for participant in participants:
                normalised = cls._safe_normalize(participant.get('phone_number', ''))
                if normalised:
                    participant_cache[normalised] = participant

            cls._coach_cache = coach_cache
            cls._participant_cache = participant_cache
            cls._cache_ts = now
        except Exception as e:
            logger.error("Error refreshing person cache: %s", e)

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
        """
        try:
            normalised = cls._safe_normalize(phone)
            if not normalised:
                return None

            cls._refresh_cache_if_stale()

            coach = cls._coach_cache.get(normalised)
            participant = cls._participant_cache.get(normalised)

            if coach and participant:
                logger.warning(
                    "Phone %s matches both a coach (id=%s) and a participant "
                    "(id=%s) — this is a data problem, returning the coach. "
                    "Investigate the duplicate phone_number value across the "
                    "coaches and participants collections.",
                    normalised, coach.get('id'), participant.get('id'),
                )
                return {**coach, 'person_type': 'coach'}

            if coach:
                return {**coach, 'person_type': 'coach'}

            if participant:
                return {**participant, 'person_type': 'participant'}

            return None
        except Exception as e:
            logger.error("Error resolving person by phone: %s", e)
            return None
