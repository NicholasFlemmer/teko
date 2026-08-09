"""QA check (one-off, no live WhatsApp needed): confirm ConversationService's
AI persona prompt resolution actually picks the right prompt per org type,
and that a per-org ai_persona_prompt override actually takes priority.

Checks:
  1. test-org-a (type=sports) resolves to the sports default prompt.
  2. test-org-b (type=ngo) resolves to the ngo default prompt.
  3. Temporarily setting test-org-b.ai_persona_prompt to a custom string
     makes it resolve to that string instead of the ngo default, then the
     field is cleared back to '' so no test data is left behind.

Refuses to run against anything other than the teko-staging-tgh project.
Read/verify only — the sole write is the temporary override in step 3,
which this script cleans up itself before exiting (including on error).

Usage:
    cd backend
    python -m scripts.qa_check_ai_persona
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv

STAGING_ENV_PATH = os.path.join(os.path.dirname(__file__), '..', '.env.staging')
EXPECTED_PROJECT_ID = 'teko-staging-tgh'
PREVIEW_CHARS = 200
OVERRIDE_TEST_ORG = 'test-org-b'
OVERRIDE_TEST_VALUE = 'QA TEST OVERRIDE PROMPT'


def preview(text):
    text = text or ''
    return text[:PREVIEW_CHARS] + ('…' if len(text) > PREVIEW_CHARS else '')


def main():
    if not os.path.exists(STAGING_ENV_PATH):
        print(f"ERROR: {STAGING_ENV_PATH} not found. Create backend/.env.staging first.")
        sys.exit(1)

    load_dotenv(dotenv_path=STAGING_ENV_PATH, override=True)
    os.environ['FIREBASE_CREDENTIALS_PATH'] = ''

    from config import Config
    from services.firebase_service import FirebaseService
    from services.conversation_service import ConversationService

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
    print("Connected to Firestore client.\n")

    # --- 1 & 2: per-type default resolution ---------------------------------
    print("=== Step 1-2: type-based default resolution ===")
    for org_id, expected_type in (('test-org-a', 'sports'), ('test-org-b', 'ngo')):
        org = FirebaseService.get_organisation(org_id)
        if not org:
            print(f"ERROR: organisations/{org_id} does not exist. Run seed_staging_test_data.py first.")
            sys.exit(1)
        actual_type = org.get('type')
        match = 'OK' if actual_type == expected_type else 'MISMATCH'
        prompt = ConversationService.get_ai_persona_prompt(org_id)
        print(f"[{org_id}] type={actual_type!r} (expected {expected_type!r}) [{match}]")
        print(f"[{org_id}] resolved prompt (first {PREVIEW_CHARS} chars):")
        print(f"    {preview(prompt)}\n")

    # --- 3: override takes priority ------------------------------------------
    print(f"=== Step 3: override on {OVERRIDE_TEST_ORG} ===")
    org_before = FirebaseService.get_organisation(OVERRIDE_TEST_ORG)
    original_value = org_before.get('ai_persona_prompt')
    print(f"[{OVERRIDE_TEST_ORG}] ai_persona_prompt before: {original_value!r}")

    try:
        FirebaseService.update_organisation(OVERRIDE_TEST_ORG, {'ai_persona_prompt': OVERRIDE_TEST_VALUE})
        prompt_with_override = ConversationService.get_ai_persona_prompt(OVERRIDE_TEST_ORG)
        print(f"[{OVERRIDE_TEST_ORG}] set ai_persona_prompt = {OVERRIDE_TEST_VALUE!r}")
        print(f"[{OVERRIDE_TEST_ORG}] resolved prompt with override set:")
        print(f"    {preview(prompt_with_override)}")
        override_ok = prompt_with_override.strip() == OVERRIDE_TEST_VALUE
        print(f"[{OVERRIDE_TEST_ORG}] override took priority: {'OK' if override_ok else 'MISMATCH'}\n")
    finally:
        FirebaseService.update_organisation(OVERRIDE_TEST_ORG, {'ai_persona_prompt': ''})
        org_after = FirebaseService.get_organisation(OVERRIDE_TEST_ORG)
        cleared_value = org_after.get('ai_persona_prompt')
        print(f"[{OVERRIDE_TEST_ORG}] ai_persona_prompt cleared back to: {cleared_value!r} "
              f"({'OK' if cleared_value == '' else 'CLEANUP FAILED'})")
        prompt_after_clear = ConversationService.get_ai_persona_prompt(OVERRIDE_TEST_ORG)
        print(f"[{OVERRIDE_TEST_ORG}] resolved prompt after clearing (should be back to ngo default):")
        print(f"    {preview(prompt_after_clear)}")

    print("\nDone.")


if __name__ == '__main__':
    main()
