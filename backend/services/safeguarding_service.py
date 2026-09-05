"""Safeguarding keyword detection, recording, and alerting on inbound
WhatsApp messages.

record_safeguarding_flag() never sends an email, never alters what a
coach/participant receives in reply, and never changes conversation flow
-- it only decides whether an inbound message's text matches a
safeguarding keyword and, if so, writes a record of that match.

send_safeguarding_alert() closes the loop: it is called exactly once,
by ConversationService.handle_incoming_message, with the flag dict that
record_safeguarding_flag() just returned -- AFTER that message's normal
reply has already been sent, so a slow or failing send can never block
or delay it. It is never called any other way and never queries
Firestore for existing/unsent flags -- see its docstring below for the
scope guarantee this gives against ever picking up a flag that predates
this feature.

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
from datetime import datetime, timezone

from firebase_admin import firestore

from services.email_service import send_safeguarding_alert_email, send_phone_collision_alert_email
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

    detected_at is captured locally (not firestore.SERVER_TIMESTAMP) so
    the exact value written is immediately available to the caller for
    the alert email, without a network read-back after the write.

    Returns the written flag as a plain dict, with the new document's id
    under 'id' -- this is the ONLY way a flag ever reaches
    send_safeguarding_alert(); see that function's docstring for why that
    guarantees a flag created before this feature shipped can never
    trigger an alert.
    """
    if not org_id:
        raise ValueError(
            f"Refusing to write a safeguarding_flags document without org_id "
            f"(person_id={person_id!r}, message_id={message_id!r})"
        )

    matched_categories = sorted(matches.keys())
    matched_terms = sorted({term for terms in matches.values() for term in terms})
    detected_at = datetime.now(timezone.utc)

    flag_data = {
        'org_id': org_id,
        'person_id': person_id,
        'person_type': person_type,
        'person_name': person_name,
        'phone_number': mask_phone(phone_number),
        'message_text': message_text,
        'matched_category': matched_categories,
        'matched_terms': matched_terms,
        'message_id': message_id,
        'detected_at': detected_at,
        'status': 'new',
        'alert_sent': False,
    }

    db = FirebaseService.get_db()
    doc_ref = db.collection(COLLECTION).document()
    doc_ref.set(flag_data)

    logger.info(
        "Safeguarding flag recorded: org_id=%s person_id=%s categories=%s",
        org_id, person_id, matched_categories,
    )

    return {'id': doc_ref.id, **flag_data}


def _recipients_for_org(org_id, org):
    """Resolve alert recipients for org_id, strictly from that org's own
    Firestore records.

    1. org.safeguarding_lead_email, if set -- the sole recipient.
    2. Otherwise every active location_admin account on that org
       (status != 'active' -- e.g. 'suspended' -- is excluded, same
       convention as the login check in routes/auth.py).

    There is deliberately no platform-level fallback and no hardcoded
    address anywhere in this function -- Teko/Triggr must never receive a
    client's safeguarding data (hard rule from the brief). The org_id
    equality check inside the location_admin loop is defence in depth:
    FirebaseService.get_all_admins_by_org already scopes its own Firestore
    query to org_id, but a safeguarding alert recipient list is exactly
    the kind of thing that must never leak cross-org even if that query
    were ever loosened later. super_admin accounts (the Triggr platform
    role -- see routes/auth.py) are never eligible; only role ==
    'location_admin' is considered.

    Returns [] if neither resolves -- the caller decides what to do with
    an empty result (log ERROR, leave alert_sent False); this function
    only resolves addresses, it never sends anything and never touches
    alert_sent itself.
    """
    lead_email = (org or {}).get('safeguarding_lead_email')
    if lead_email:
        return [lead_email]

    admins = FirebaseService.get_all_admins_by_org(org_id)
    recipients = []
    for admin in admins:
        if admin.get('org_id') != org_id:
            continue
        if admin.get('role') != 'location_admin':
            continue
        if admin.get('status', 'active') != 'active':
            continue
        email = admin.get('email')
        if email:
            recipients.append(email)
    return recipients


def send_safeguarding_alert(flag):
    """Send the alert email(s) for one just-created safeguarding flag.

    MUST be called only from ConversationService.handle_incoming_message,
    exactly once, immediately with the dict record_safeguarding_flag()
    just returned -- and only after that message's normal reply has
    already been sent, so a slow or failing send here can never block or
    delay it.

    SCOPE GUARANTEE against ever alerting on a pre-existing flag: this
    function takes the flag to alert on as a plain argument -- it never
    runs a Firestore query of its own to find flags (no `.where(...)`,
    no `.stream()` over the safeguarding_flags collection anywhere in
    this module). The only write it performs against an existing
    document is a single `.document(flag['id']).update(...)` once sending
    succeeds. A flag created before this feature shipped is therefore
    structurally unreachable here: nothing ever iterates the collection
    looking for alert_sent == False, so nothing can ever pick one up.

    Never raises -- every failure path (org/recipient resolution failure,
    no recipients, send failure) is caught here and logged at ERROR with
    the flag ID; alert_sent is simply left False (its value from
    record_safeguarding_flag) for that to be investigated manually. Not
    retried inline, per the brief.
    """
    flag_id = flag['id']
    org_id = flag['org_id']

    try:
        org = FirebaseService.get_organisation(org_id)
        recipients = _recipients_for_org(org_id, org)
    except Exception:
        logger.error(
            "Safeguarding alert: failed to resolve recipients for flag_id=%s org_id=%s",
            flag_id, org_id, exc_info=True,
        )
        return

    if not recipients:
        logger.error(
            "Safeguarding alert: no recipients resolved for flag_id=%s org_id=%s -- "
            "no safeguarding_lead_email set and no active location_admin accounts "
            "found. alert_sent left False.",
            flag_id, org_id,
        )
        return

    org_name = (org or {}).get('name') or 'your organisation'
    detected_at_display = flag['detected_at'].strftime('%Y-%m-%d %H:%M:%S UTC')

    sent_to = []
    try:
        for recipient in recipients:
            send_safeguarding_alert_email(
                to_email=recipient,
                org_name=org_name,
                flag_id=flag_id,
                person_name=flag.get('person_name'),
                person_type=flag.get('person_type'),
                phone_masked=flag.get('phone_number'),
                message_text=flag.get('message_text'),
                matched_categories=flag.get('matched_category', []),
                matched_terms=flag.get('matched_terms', []),
                detected_at_display=detected_at_display,
            )
            sent_to.append(recipient)
    except Exception:
        logger.error(
            "Safeguarding alert: send failed for flag_id=%s org_id=%s after sending "
            "to %d/%d resolved recipients -- alert_sent left False, not retried inline",
            flag_id, org_id, len(sent_to), len(recipients), exc_info=True,
        )
        return

    db = FirebaseService.get_db()
    db.collection(COLLECTION).document(flag_id).update({
        'alert_sent': True,
        'sent_at': firestore.SERVER_TIMESTAMP,
        'alert_recipients': recipients,
    })

    logger.info(
        "Safeguarding alert sent: flag_id=%s org_id=%s recipients=%d",
        flag_id, org_id, len(recipients),
    )


def send_phone_collision_alert(colliding_org_ids, phone_number):
    """Alert every colliding org's safeguarding lead (or active
    location_admins) that a safeguarding-flagged message arrived from a
    phone number registered to more than one org's coach — WITHOUT
    identifying who sent it, what they said, or which keyword matched.

    Exists because PersonService.resolve() refuses to name a sender when
    their number collides across orgs (see
    PersonService._coach_collisions) — so a genuine disclosure from that
    number must still be able to reach a human, without guessing which
    of the colliding orgs it "really" belongs to, and without letting
    one org see anything that might be another org's data. Every
    colliding org gets its own, identical, content-free notice: only the
    org name and the phone number's last 4 digits (see
    send_phone_collision_alert_email) — no message text, no matched
    category or term, no full phone number.

    Recipients are resolved exactly like send_safeguarding_alert does
    (org's safeguarding_lead_email, else active location_admins), via
    the same _recipients_for_org helper, so the two paths can never
    drift apart.

    Writes nothing to Firestore — there is no single correct org_id to
    record a flag document against here, only a set of orgs to notify.
    Never raises: every failure (org/recipient resolution, send failure)
    is caught and logged at ERROR per org, same as send_safeguarding_alert.
    """
    phone_masked = mask_phone(phone_number)

    for org_id in colliding_org_ids:
        try:
            org = FirebaseService.get_organisation(org_id)
            recipients = _recipients_for_org(org_id, org)
        except Exception:
            logger.error(
                "Phone-collision safeguarding alert: failed to resolve recipients for org_id=%s",
                org_id, exc_info=True,
            )
            continue

        if not recipients:
            logger.error(
                "Phone-collision safeguarding alert: no recipients resolved for org_id=%s -- "
                "no safeguarding_lead_email set and no active location_admin accounts found.",
                org_id,
            )
            continue

        org_name = (org or {}).get('name') or 'your organisation'
        try:
            for recipient in recipients:
                send_phone_collision_alert_email(
                    to_email=recipient,
                    org_name=org_name,
                    phone_masked=phone_masked,
                )
            logger.info(
                "Phone-collision safeguarding alert sent: org_id=%s recipients=%d",
                org_id, len(recipients),
            )
        except Exception:
            logger.error(
                "Phone-collision safeguarding alert: send failed for org_id=%s",
                org_id, exc_info=True,
            )
