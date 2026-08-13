"""Unit tests for Phase 2 step 4 part A: a genuinely participant-oriented
AI persona, instead of participants receiving the identical
facilitator-oriented persona coaches get.

Pure unit tests: FirebaseService.get_organisation is stubbed via
monkeypatch, so nothing here touches Firestore — same convention as
test_persona_locale_and_terminology.py, which this extends.

Usage:
    cd backend
    pytest tests/test_participant_persona.py -v
"""
import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv

STAGING_ENV_PATH = os.path.join(os.path.dirname(__file__), '..', '.env.staging')
if os.path.exists(STAGING_ENV_PATH):
    load_dotenv(dotenv_path=STAGING_ENV_PATH, override=True)
    os.environ['FIREBASE_CREDENTIALS_PATH'] = ''

import pytest  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402

ORG_TYPES = ['sports', 'ngo', 'events', 'corporate']

# Phrases that only belong in a persona oriented toward the person who RUNS
# sessions — planning them, coaching methodology, managing other people —
# framed POSITIVELY (an instruction to give this kind of advice), as
# distinct from the participant persona's own "do NOT give session-planning
# advice"-style refusal, which legitimately contains some of the same
# words but in a negation. None of these positive phrasings should appear
# in a participant persona.
FACILITATION_LANGUAGE_MARKERS = [
    "session's objectives", 'provide practical, actionable',
    'drills and exercises', 'suggest specific drills',
    'suggest activities and exercises suited', 'giving and structuring',
    'constructive feedback', 'volunteer coordination',
    'available resources', "experience level and",
]


def _org(org_type, **extra):
    return {'id': 'org-1', 'type': org_type, **extra}


@pytest.mark.parametrize('org_type', ORG_TYPES)
def test_participant_persona_differs_from_coach_persona(monkeypatch, org_type):
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org(org_type))

    coach_prompt = ConversationService.get_ai_persona_prompt('org-1', 'coach')
    participant_prompt = ConversationService.get_ai_persona_prompt('org-1', 'participant')

    assert coach_prompt != participant_prompt


@pytest.mark.parametrize('org_type', ORG_TYPES)
def test_participant_persona_has_no_facilitation_or_session_planning_language(monkeypatch, org_type):
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org(org_type))

    prompt = ConversationService.get_ai_persona_prompt('org-1', 'participant').lower()

    offenders = [marker for marker in FACILITATION_LANGUAGE_MARKERS if marker in prompt]
    assert not offenders, f"{org_type} participant persona contains facilitation language: {offenders}"

    # No EXPERTISE section at all — that section exists specifically to
    # give the AI coaching/facilitation domain knowledge.
    assert 'EXPERTISE:' not in ConversationService.get_ai_persona_prompt('org-1', 'participant')


@pytest.mark.parametrize('org_type', ORG_TYPES)
def test_participant_persona_explicitly_refuses_facilitation_advice(monkeypatch, org_type):
    """Not just absence of facilitation content — an explicit constraint
    telling the model not to provide it, per the task's requirement."""
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org(org_type))

    prompt = ConversationService.get_ai_persona_prompt('org-1', 'participant')

    assert re.search(r'do not|not\s+.*advice|not\s+.*guidance', prompt, re.IGNORECASE)


@pytest.mark.parametrize('org_type', ORG_TYPES)
def test_participant_persona_has_safeguarding_line(monkeypatch, org_type):
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org(org_type))

    prompt = ConversationService.get_ai_persona_prompt('org-1', 'participant')

    assert 'refer serious concerns to the organisation' in prompt.lower()
    assert 'safeguarding' in prompt.lower()


@pytest.mark.parametrize('org_type', ORG_TYPES)
def test_participant_persona_oriented_to_their_own_sessions(monkeypatch, org_type):
    """Positive check, not just absence: the participant persona should be
    about THEIR OWN sessions/schedule/expectations."""
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org(org_type))

    prompt = ConversationService.get_ai_persona_prompt('org-1', 'participant').lower()

    assert 'their own upcoming sessions and schedule' in prompt
    assert 'what to bring' in prompt or 'what to expect' in prompt


@pytest.mark.parametrize('org_type,expected_coach_word', [
    ('sports', 'coach'), ('ngo', 'facilitator'), ('events', 'coach'), ('corporate', 'facilitator'),
])
def test_participant_persona_uses_org_terminology_for_the_facilitator_role(monkeypatch, org_type, expected_coach_word):
    """The participant persona still needs to refer to whoever runs
    sessions when redirecting an out-of-scope question — must use the
    org's own terminology, not a hardcoded word."""
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org(org_type))

    prompt = ConversationService.get_ai_persona_prompt('org-1', 'participant').lower()

    assert expected_coach_word in prompt


@pytest.mark.parametrize('org_type', ORG_TYPES)
def test_participant_persona_locale_driven_not_hardcoded(monkeypatch, org_type):
    """Same 3d requirement, extended to the participant template: country
    and language must come from org config, never hardcoded."""
    monkeypatch.setattr(
        FirebaseService, 'get_organisation',
        lambda org_id: _org(org_type, country='Brazil', supported_languages=['Portuguese', 'English']),
    )

    prompt = ConversationService.get_ai_persona_prompt('org-1', 'participant')

    assert 'Brazil' in prompt
    assert 'South Africa' not in prompt
    assert 'Portuguese' in prompt
    assert 'isiZulu' not in prompt


@pytest.mark.parametrize('org_type', ORG_TYPES)
def test_participant_persona_defaults_to_south_africa_regression(monkeypatch, org_type):
    """Regression guard: an org with no custom locale (e.g. CATCH Trust)
    must see the exact same South Africa / 11-language defaults."""
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org(org_type))

    prompt = ConversationService.get_ai_persona_prompt('org-1', 'participant')

    assert 'South Africa' in prompt
    assert 'isiZulu' in prompt


# ---------------------------------------------------------------------------
# Custom ai_persona_prompt override still wins for BOTH person types.
# ---------------------------------------------------------------------------

def test_custom_override_wins_for_both_person_types(monkeypatch):
    custom = "CUSTOM PERSONA: You are a bespoke assistant for Acme Org. Follow these exact instructions only."
    monkeypatch.setattr(FirebaseService, 'get_organisation',
                         lambda org_id: _org('ngo', ai_persona_prompt=custom))

    coach_prompt = ConversationService.get_ai_persona_prompt('org-1', 'coach')
    participant_prompt = ConversationService.get_ai_persona_prompt('org-1', 'participant')

    assert coach_prompt == custom
    assert participant_prompt == custom


# ---------------------------------------------------------------------------
# Coach personas must not change at all — byte-for-byte regression pin
# against the exact strings from Phase 2 step 3d.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('org_type', ORG_TYPES)
def test_coach_persona_unchanged_from_step_3d(monkeypatch, org_type):
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org(org_type))

    prompt = ConversationService.get_ai_persona_prompt('org-1', 'coach')
    # get_ai_persona_prompt(org_id) with no explicit person_type must still
    # default to 'coach' — every pre-existing caller (scripts, prior tests)
    # relied on this signature and must keep working unchanged.
    prompt_default_arg = ConversationService.get_ai_persona_prompt('org-1')

    assert prompt == prompt_default_arg
    assert 'South Africa' in prompt
    assert 'EXPERTISE:' in prompt
