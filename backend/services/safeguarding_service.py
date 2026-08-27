"""Safeguarding keyword detection on inbound WhatsApp messages.

DETECTION AND RECORDING ONLY. This module never sends an email, never
alters what a coach/participant receives in reply, and never changes
conversation flow -- it only decides whether an inbound message's text
matches a safeguarding keyword and, if so, writes a record of that match.
Alerting (step 4) is a separate, later piece of work; alert_sent on the
written record defaults to False for that step to pick up.

Matching: whole-word-boundary, case-insensitive, tolerant of surrounding
punctuation -- deliberately NOT naive substring matching. A multi-word
phrase like "hit me" is escaped word-by-word and joined on `\\s+` so
normal spacing variations still match, then wrapped in `\\b...\\b` so
"draped" never matches "raped" and a run-together word never matches a
two-word phrase. Every keyword phrase is treated as its own independent
signal: no confidence scoring, no suppression, no picking the "most
likely" category when more than one matches. That is a deliberate
constraint from the brief, not an oversight -- it is not this system's
job to decide whether a concern is real.

KNOWN LIMITATION, not silently patched over: because "hit me" is an
unqualified two-word phrase in the client's own starter keyword list, it
will also fire on genuinely benign sentences that happen to contain
those same words in sequence -- e.g. "coach hit me a great throwdown
today" (a real cricket-context sentence). This false positive is
accepted deliberately: "hit me" is the highest-value phrase on the
list. See tests/test_safeguarding_detection.py for this pinned as an
expected failure (xfail), not silently suppressed -- suppressing it
would mean writing confidence/exception logic, which the brief
explicitly forbids.
"""
import logging
import re

from firebase_admin import firestore

from services.firebase_service import FirebaseService
from services.safeguarding_keywords import SAFEGUARDING_KEYWORDS
from utils.phone import mask_phone

logger = logging.getLogger(__name__)

COLLECTION = 'safeguarding_flags'


def _compile_patterns():
    """One compiled regex per (category, term) pair, built once at import
    time -- not per call. Each word in a phrase is escaped individually
    and joined on `\\s+` (tolerant of any run of whitespace between
    words), then the whole phrase is wrapped in word boundaries so
    surrounding punctuation never blocks a match and a longer word that
    merely contains the phrase's letters never falsely matches."""
    compiled = {}
    for category, terms in SAFEGUARDING_KEYWORDS.items():
        term_patterns = []
        for term in terms:
            words = term.split()
            escaped_phrase = r'\s+'.join(re.escape(word) for word in words)
            pattern = re.compile(r'\b' + escaped_phrase + r'\b', re.IGNORECASE)
            term_patterns.append((term, pattern))
        compiled[category] = term_patterns
    return compiled


_COMPILED_PATTERNS = _compile_patterns()


def detect_safeguarding_matches(message_text):
    """Scan message_text against every category's keyword list.

    Returns {category: [matched_term, ...]} for every category that had
    at least one match -- a message matching terms in more than one
    category returns ALL of them, never just one. Returns {} (falsy) for
    no matches or empty/falsy input. Pure function, no I/O -- safe to
    call on its own in tests without touching Firestore.
    """
    if not message_text:
        return {}

    matches = {}
    for category, term_patterns in _COMPILED_PATTERNS.items():
        matched_terms = [term for term, pattern in term_patterns if pattern.search(message_text)]
        if matched_terms:
            matches[category] = matched_terms
    return matches


def record_safeguarding_flag(org_id, person_id, person_type, person_name, phone_number,
                              message_text, message_id, matches):
    """Write one safeguarding_flags document recording every matched
    category and term from `matches` (as returned by
    detect_safeguarding_matches) -- never just the first/highest one.

    org_id is REQUIRED and this raises if it's falsy, rather than writing
    an unscoped document -- this collection must be org-scoped from the
    write itself, the same lesson check_in_tokens had to learn after the
    fact (see tests/test_token_org_id_scoping.py). Raises on any Firestore
    failure too; this function does NOT catch its own errors -- the
    caller (ConversationService.handle_incoming_message) is responsible
    for wrapping the call so a failure here can never block the reply,
    while still logging the failure at ERROR. See that call site for the
    wrapping and constraint 2 (never fail silently) in the phase brief.

    message_text is stored EXACTLY as received -- no paraphrasing, no
    summarising, no truncation, per the client's policy on near-verbatim
    records.

    phone_number is stored masked (mask_phone -- last 4 digits only),
    the same convention used for every other phone number that reaches a
    log line or a stored record elsewhere in this codebase. person_id +
    person_type already uniquely identify the individual (a foreign key
    into the coaches/participants collection, which does hold the full
    number) -- the flag record itself doesn't need the raw number to
    identify who sent it, so it doesn't carry one.
    """
    if not org_id:
        raise ValueError(
            f"Refusing to write a safeguarding_flags document without org_id "
            f"(person_id={person_id!r}, message_id={message_id!r})"
        )

    matched_categories = sorted(matches.keys())
    matched_terms = sorted({term for terms in matches.values() for term in terms})

    db = FirebaseService.get_db()
    doc_ref = db.collection(COLLECTION).document()
    doc_ref.set({
        'org_id': org_id,
        'person_id': person_id,
        'person_type': person_type,
        'person_name': person_name,
        'phone_number': mask_phone(phone_number),
        'message_text': message_text,
        'matched_category': matched_categories,
        'matched_terms': matched_terms,
        'message_id': message_id,
        'detected_at': firestore.SERVER_TIMESTAMP,
        'status': 'new',
        'alert_sent': False,
    })

    logger.info(
        "Safeguarding flag recorded: org_id=%s person_id=%s categories=%s",
        org_id, person_id, matched_categories,
    )
