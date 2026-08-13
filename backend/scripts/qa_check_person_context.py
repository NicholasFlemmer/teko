"""QA check (one-off, no live WhatsApp needed): print the ACTUAL assembled
persona prompt, conversation-history role label, and reply text the AI
conversation path (Phase 2 step 3) produces — for a coach and a
participant, at a sports org and an ngo org — so a human can read the real
wording rather than a pass/fail summary.

Follows the same approach as qa_check_ai_persona.py: read real Firestore
data from teko-staging-tgh, drive ConversationService directly, print full
untruncated output.

WHAT'S REAL vs STUBBED (this script only — no application code is
modified):
  - Org lookup, persona prompt resolution, terminology resolution, RAG
    content, and person context all run through the real
    FirebaseService/ConversationService code exactly as the webhook uses
    them.
  - GeminiService.generate_custom_message is wrapped (not replaced) so the
    real underlying call still happens — this script only intercepts the
    prompt argument to print it, then forwards the call to the real
    implementation, with a 20s timeout as a safety net (Gemini's own
    client has no timeout wired up).
  - WhatsAppService.send_message is replaced with a local capture so this
    script never attempts a real WhatsApp send to the fake seeded phone
    numbers.
  - ConversationService.save_message is replaced with a no-op so this
    script never leaves stray documents in staging Firestore's
    `conversations` collection.
  - ConversationService.get_conversation_history is replaced with a fixed
    one-turn example (there is no real history for these QA-only phone
    numbers) so the printed prompts visibly demonstrate the history role
    label in context, not just as a separately-stated value.

GEMINI_API_KEY in this environment's .env files is a placeholder, not a
real key. Real Gemini calls will fail and GeminiService's own
already-built fallback behaviour will kick in — that IS the actual
behaviour of the real code path in this environment, so it's printed
as-is with a clear banner, not faked.

Checks:
  1-4. Four combinations (org x person_type) — for each, prints an explicit
       CONTEXT LOAD STATUS line (OK / DEGRADED / empty, for both person
       context and RAG context, with the actual team/session/content/URL
       item counts pulled), then the fully assembled persona prompt
       (untruncated), the history role label, and actual replies to a
       knowledge-base question, a trainer-only command (/attendance),
       /help, and an unregistered sender. A degraded/empty context is
       never silently absent from this output — a Phase 2 step 3 run
       hid a real "no index" failure behind an empty section; this
       status line exists so that can't happen again unnoticed.
  5. ai_persona_prompt override on test-org-b: confirms it wins for BOTH
     person types, then confirms clearing it falls back to the ngo
     default. Cleans up its own write, including on error — same pattern
     as qa_check_ai_persona.py.
  6. RAG context assembled for an Org B participant: confirms only Org B
     content is present; prints how many items were pulled and which org
     each belongs to.

Refuses to run against anything other than the teko-staging-tgh project.
Read-only except for the temporary override in step 5, which cleans up
after itself.

Usage:
    cd backend
    python -m scripts.qa_check_person_context
"""
import sys
import os
import concurrent.futures
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv

STAGING_ENV_PATH = os.path.join(os.path.dirname(__file__), '..', '.env.staging')
EXPECTED_PROJECT_ID = 'teko-staging-tgh'
OVERRIDE_TEST_ORG = 'test-org-b'
OVERRIDE_TEST_VALUE = 'QA TEST OVERRIDE PROMPT — Phase 2 step 3 person-context check'
GEMINI_CALL_TIMEOUT = 20  # seconds — this script's own safety net; GeminiService has none
UNREGISTERED_PHONE = '27000009999'
EXAMPLE_HISTORY_TURN = 'What did we cover last time?'


def section(title):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def subsection(title):
    print(f"\n--- {title} ---")


def main():
    if not os.path.exists(STAGING_ENV_PATH):
        print(f"ERROR: {STAGING_ENV_PATH} not found. Create backend/.env.staging first.")
        sys.exit(1)

    load_dotenv(dotenv_path=STAGING_ENV_PATH, override=True)
    os.environ['FIREBASE_CREDENTIALS_PATH'] = ''

    from config import Config
    from services.firebase_service import FirebaseService
    from services.conversation_service import ConversationService
    from services.gemini_service import GeminiService
    from services.whatsapp_service import WhatsAppService

    project_id = Config.FIREBASE_PROJECT_ID
    print(f"Target Firebase project: {project_id}")
    if project_id != EXPECTED_PROJECT_ID:
        print(
            f"ERROR: expected FIREBASE_PROJECT_ID={EXPECTED_PROJECT_ID}, got "
            f"'{project_id}'. Aborting — refusing to run against a different project."
        )
        sys.exit(1)

    db = FirebaseService.initialize()
    if db is None:
        print("ERROR: Firebase initialization failed — see logs above.")
        sys.exit(1)
    print("Connected to Firestore client.")

    api_key = Config.GEMINI_API_KEY or ''
    key_looks_real = bool(api_key) and 'your-gemini-api-key' not in api_key.lower()
    if not key_looks_real:
        print(
            "\nNOTE: GEMINI_API_KEY in this environment is a placeholder, not a real key.\n"
            "      Knowledge-base question replies below will show GeminiService's own\n"
            "      configured fallback text, not a real generated answer. The ASSEMBLED\n"
            "      PROMPT that would have been sent is still the real one — that's what\n"
            "      this script exists to verify."
        )

    # --- Wire up seeded test data -------------------------------------------
    from scripts.seed_staging_test_data import _doc_ids
    ORG_A, ORG_B = 'test-org-a', 'test-org-b'  # sports, ngo
    IDS_A, IDS_B = _doc_ids(ORG_A), _doc_ids(ORG_B)

    def _require(record, label):
        if not record:
            print(f"ERROR: {label} not found. Run `python -m scripts.seed_staging_test_data` first.")
            sys.exit(1)
        return record

    coach_a = _require(FirebaseService.get_coach(IDS_A['coach_1'], ORG_A), f"{ORG_A} coach_1")
    participant_a = _require(FirebaseService.get_participant(ORG_A, IDS_A['participant_1']), f"{ORG_A} participant_1")
    coach_b = _require(FirebaseService.get_coach(IDS_B['coach_1'], ORG_B), f"{ORG_B} coach_1")
    participant_b = _require(FirebaseService.get_participant(ORG_B, IDS_B['participant_1']), f"{ORG_B} participant_1")

    print(f"[{ORG_A}] coach: {coach_a['name']!r} ({coach_a['phone_number']})")
    print(f"[{ORG_A}] participant: {participant_a['name']!r} ({participant_a['phone_number']})")
    print(f"[{ORG_B}] coach: {coach_b['name']!r} ({coach_b['phone_number']})")
    print(f"[{ORG_B}] participant: {participant_b['name']!r} ({participant_b['phone_number']})")

    # --- Stubs (this process only — no application code modified) ----------
    sent_box = {}
    prompt_box = {}

    def _fake_send(phone_number, message_text, check_in_url=None):
        sent_box['phone_number'] = phone_number
        sent_box['message_text'] = message_text
        return {'success': True}

    _real_gemini_generate = GeminiService.generate_custom_message.__func__

    def _capturing_gemini(prompt):
        prompt_box['prompt'] = prompt
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_real_gemini_generate, GeminiService, prompt)
            try:
                return future.result(timeout=GEMINI_CALL_TIMEOUT)
            except concurrent.futures.TimeoutError:
                return (f"[QA SCRIPT TIMEOUT] Gemini call did not return within "
                         f"{GEMINI_CALL_TIMEOUT}s — network/credentials issue in this environment.")

    WhatsAppService.send_message = _fake_send
    GeminiService.generate_custom_message = _capturing_gemini
    ConversationService.save_message = lambda phone, role, content: None
    ConversationService.get_conversation_history = lambda phone, limit=10: [
        {'role': 'user', 'content': EXAMPLE_HISTORY_TURN, 'timestamp': None}
    ]

    def drive(phone, text):
        """Call the real webhook entry point and capture what it would have
        sent via WhatsApp, and the prompt it built for Gemini (if any)."""
        sent_box.clear()
        prompt_box.clear()
        ConversationService.clear_pending_attendance(phone)  # defensive reset between calls
        ConversationService.handle_incoming_message(phone, text, message_id='qa-check-person-context')
        return sent_box.get('message_text', '(no message was sent)'), prompt_box.get('prompt')

    CONTEXT_DEGRADED_MARKER = '[SYSTEM NOTE:'

    def _status_label(context_text):
        if CONTEXT_DEGRADED_MARKER in context_text:
            return 'DEGRADED'
        if context_text:
            return 'OK'
        return 'empty (nothing to load)'

    def report_context_status(org_id, person, person_type):
        """Explicit, ground-truth report of whether context loaded cleanly
        or degraded, plus the actual item counts pulled — called directly,
        not inferred from whatever ended up in a Gemini prompt, so a
        degraded/empty section can never be silently missed here."""
        print("\n>>> CONTEXT LOAD STATUS <<<")

        person_context = ConversationService.load_person_context(person['id'], org_id, person_type)
        person_status = _status_label(person_context)

        if person_type == 'coach':
            all_teams = FirebaseService.get_all_teams(org_id)
            coach_teams = [t for t in all_teams if person['id'] in (t.get('coach_ids') or [])]
            player_count = sum(
                len(FirebaseService.get_all_players(org_id, team_id=t.get('id'))) for t in coach_teams
            )
            today_str = date.today().strftime('%Y-%m-%d')
            session_count = len(FirebaseService.get_all_sessions(org_id, coach_id=person['id'], start_date=today_str))
            print(f"Person context (coach): {person_status}")
            print(f"  Teams pulled: {len(coach_teams)} | Players pulled: {player_count} | "
                  f"Upcoming sessions pulled: {session_count}")
        else:
            print(f"Person context (participant): {person_status}")
            print("  Teams/sessions: N/A — participants have no roster relationship yet (Phase 2 step 3)")

        if person_status == 'DEGRADED':
            for line in person_context.split('\n'):
                if CONTEXT_DEGRADED_MARKER in line:
                    print(f"  >> {line.strip()}")

        rag_context = ConversationService.load_rag_context(org_id)
        rag_status = _status_label(rag_context)
        content_count = len(FirebaseService.get_all_content(org_id))
        url_count = len(FirebaseService.get_all_urls(org_id))
        print(f"RAG context: {rag_status}")
        print(f"  Content items pulled: {content_count} | URL items pulled: {url_count}")
        if rag_status == 'DEGRADED':
            for line in rag_context.split('\n'):
                if CONTEXT_DEGRADED_MARKER in line:
                    print(f"  >> {line.strip()}")

    # --- Unregistered sender (identity resolution doesn't depend on org or
    # person_type, so this is genuinely the same result in every combo —
    # computed once, printed per combo below) --------------------------------
    unregistered_reply, _ = drive(UNREGISTERED_PHONE, 'hello')

    combos = [
        (ORG_A, 'sports', 'coach', coach_a),
        (ORG_A, 'sports', 'participant', participant_a),
        (ORG_B, 'ngo', 'coach', coach_b),
        (ORG_B, 'ngo', 'participant', participant_b),
    ]

    for org_id, org_type, person_type, person in combos:
        phone = person['phone_number']
        name = person['name']
        section(f"{org_id} ({org_type}) — {person_type}: {name} ({phone})")

        report_context_status(org_id, person, person_type)

        subsection("Knowledge-base question reply + assembled persona prompt")
        kb_reply, prompt = drive(phone, "What is a good warm-up drill for beginners?")
        print("FULL ASSEMBLED PROMPT SENT TO GEMINI:")
        print(prompt if prompt is not None else '(no prompt was built — see reply below for why)')
        print("\nREPLY TEXT:")
        print(kb_reply)

        # The role label for a past user turn is the same role_word the
        # prompt above already shows in its "Recent conversation:" section
        # (EXAMPLE_HISTORY_TURN is stubbed history) — pulled back out here
        # so it's also stated explicitly, not just visible in context.
        terminology = FirebaseService.get_org_terminology(org_id)
        role_word = terminology['coach_singular'] if person_type == 'coach' else terminology['player_singular']
        print(f"\nCONVERSATION HISTORY ROLE LABEL for a past user turn: {role_word!r}")

        subsection("Trainer-only command reply (/attendance)")
        attendance_reply, _ = drive(phone, '/attendance')
        print(attendance_reply)

        subsection("/help reply")
        help_reply, _ = drive(phone, '/help')
        print(help_reply)

        subsection("Unregistered-sender reply (same phone used for all combinations)")
        print(unregistered_reply)

    # --- ai_persona_prompt override check on test-org-b ---------------------
    section(f"Override check: {OVERRIDE_TEST_ORG}.ai_persona_prompt")
    org_before = FirebaseService.get_organisation(OVERRIDE_TEST_ORG)
    original_value = org_before.get('ai_persona_prompt')
    print(f"[{OVERRIDE_TEST_ORG}] ai_persona_prompt before: {original_value!r}")

    try:
        FirebaseService.update_organisation(OVERRIDE_TEST_ORG, {'ai_persona_prompt': OVERRIDE_TEST_VALUE})
        print(f"[{OVERRIDE_TEST_ORG}] set ai_persona_prompt = {OVERRIDE_TEST_VALUE!r}\n")

        for person_type, person in (('coach', coach_b), ('participant', participant_b)):
            subsection(f"{OVERRIDE_TEST_ORG} — {person_type} with override active")
            _, prompt = drive(person['phone_number'], "What is a good warm-up drill for beginners?")
            print("FULL ASSEMBLED PROMPT SENT TO GEMINI:")
            print(prompt if prompt is not None else '(no prompt was built)')
            override_present = bool(prompt) and prompt.startswith(OVERRIDE_TEST_VALUE)
            print(f"\nOverride text leads the prompt: {'YES' if override_present else 'NO — CHECK THIS'}")
    finally:
        FirebaseService.update_organisation(OVERRIDE_TEST_ORG, {'ai_persona_prompt': ''})
        org_after = FirebaseService.get_organisation(OVERRIDE_TEST_ORG)
        cleared_value = org_after.get('ai_persona_prompt')
        print(f"\n[{OVERRIDE_TEST_ORG}] ai_persona_prompt cleared back to: {cleared_value!r} "
              f"({'OK' if cleared_value == '' else 'CLEANUP FAILED — CHECK MANUALLY'})")

    subsection(f"{OVERRIDE_TEST_ORG} — coach, after clearing (should be back to ngo default)")
    prompt_after_clear = ConversationService.get_ai_persona_prompt(OVERRIDE_TEST_ORG)
    print(prompt_after_clear)
    ngo_default_restored = prompt_after_clear.startswith(
        ConversationService.DEFAULT_AI_PERSONA_PROMPTS['ngo'][:80]
    )
    print(f"\nFell back to ngo type default: {'YES' if ngo_default_restored else 'NO — CHECK THIS'}")

    # --- RAG isolation for an Org B participant ------------------------------
    section(f"RAG context isolation for an {ORG_B} participant")
    content_items = FirebaseService.get_all_content(ORG_B)
    url_items = FirebaseService.get_all_urls(ORG_B)
    print(f"Content items pulled for org_id={ORG_B!r}: {len(content_items)}")
    for item in content_items:
        print(f"  - id={item.get('id')} org_id={item.get('org_id')!r} title={item.get('title')!r}")
    print(f"URL items pulled for org_id={ORG_B!r}: {len(url_items)}")
    for item in url_items:
        print(f"  - id={item.get('id')} org_id={item.get('org_id')!r} title={item.get('title')!r}")

    wrong_org_items = [i for i in (content_items + url_items) if i.get('org_id') != ORG_B]
    print(f"\nItems NOT belonging to {ORG_B}: {len(wrong_org_items)} "
          f"({'OK — isolation holds' if not wrong_org_items else 'LEAK — CHECK THIS'})")

    rag_context = ConversationService.load_rag_context(ORG_B)
    print(f"\nAssembled RAG context length: {len(rag_context)} chars")
    contains_org_b = 'Org B confidential coaching notes' in rag_context
    contains_org_a = 'Org A confidential coaching notes' in rag_context
    print(f"Contains Org B's own content marker: {'YES' if contains_org_b else 'NO — CHECK THIS'}")
    print(f"Contains Org A's content marker: {'NO — OK' if not contains_org_a else 'YES — LEAK, CHECK THIS'}")

    section("Done.")


if __name__ == '__main__':
    main()
