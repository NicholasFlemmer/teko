"""Unit tests for Phase 2 step 3d items 3a/3b: the AI persona prompt no
longer hardcodes "coach" for org types whose terminology resolves to
something else (Facilitator), and no longer hardcodes South Africa / the
11 official SA languages — both are now driven by org config
(FirebaseService.get_org_terminology / get_org_locale), defaulting to the
exact same South African values every org had before country/
supported_languages existed as fields, so an unconfigured org (e.g. CATCH
Trust) sees no behaviour change.

Pure unit tests: FirebaseService.get_organisation is stubbed via
monkeypatch, so nothing here touches Firestore — same convention as
test_person_service.py.

Usage:
    cd backend
    pytest tests/test_persona_locale_and_terminology.py -v
"""
import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) now lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

import pytest  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402

BARE_COACH_RE = re.compile(r'\bcoach(es)?\b', re.IGNORECASE)


def _org(org_type, **extra):
    return {'id': 'org-1', 'type': org_type, **extra}


# ---------------------------------------------------------------------------
# Item 3a: "coach" hardcoding in types whose terminology isn't "Coach".
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('org_type', ['ngo', 'corporate'])
def test_facilitator_type_personas_never_say_bare_coach(monkeypatch, org_type):
    """ngo and corporate both resolve coach_singular to 'Facilitator' —
    neither default persona should say the bare word 'coach'/'coaches'
    anywhere (domain terms like 'coaching methodologies' don't match the
    word-boundary regex, so they're allowed to remain)."""
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org(org_type))

    prompt = ConversationService.get_ai_persona_prompt('org-1')

    assert not BARE_COACH_RE.search(prompt), (
        f"{org_type} persona still says 'coach' despite its terminology resolving to Facilitator:\n{prompt}"
    )
    assert 'facilitator' in prompt.lower()


@pytest.mark.parametrize('org_type', ['sports', 'events'])
def test_coach_type_personas_regression_still_say_coach(monkeypatch, org_type):
    """sports and events both resolve coach_singular to 'Coach' — this was
    never the bug, so their default wording must be unchanged."""
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org(org_type))

    prompt = ConversationService.get_ai_persona_prompt('org-1')

    assert BARE_COACH_RE.search(prompt), f"{org_type} persona should still address the coach as 'coach'."
    assert 'facilitator' not in prompt.lower()


def test_custom_ai_persona_prompt_override_is_never_templated(monkeypatch):
    """An org's own Organisation.ai_persona_prompt is returned verbatim —
    even if it happens to contain literal curly braces, it must never be
    passed through .format() (which would raise or silently mangle it)."""
    custom = "CUSTOM PROMPT with a literal {brace} in it that isn't a template placeholder."
    monkeypatch.setattr(FirebaseService, 'get_organisation',
                         lambda org_id: _org('ngo', ai_persona_prompt=custom))

    prompt = ConversationService.get_ai_persona_prompt('org-1')

    assert prompt == custom


# ---------------------------------------------------------------------------
# Item 3b: country / language hardcoding.
# ---------------------------------------------------------------------------

def test_org_without_locale_config_defaults_to_south_africa_regression(monkeypatch):
    """Regression guard: an org with no country/supported_languages set
    (e.g. CATCH Trust, unchanged since before this fix) must still get
    the exact same South Africa / 11-language wording as before."""
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org('sports'))

    prompt = ConversationService.get_ai_persona_prompt('org-1')

    assert 'South Africa' in prompt
    assert 'isiZulu' in prompt
    assert 'Afrikaans' in prompt


def test_non_sa_org_country_reflected_in_persona_not_south_africa(monkeypatch):
    monkeypatch.setattr(
        FirebaseService, 'get_organisation',
        lambda org_id: _org('ngo', country='Brazil', supported_languages=['Portuguese', 'English']),
    )

    prompt = ConversationService.get_ai_persona_prompt('org-1')

    assert 'Brazil' in prompt
    assert 'South Africa' not in prompt
    assert 'Portuguese' in prompt
    assert 'isiZulu' not in prompt, "SA-specific language list must not leak into a non-SA org's prompt."


@pytest.mark.parametrize('org_type', ['sports', 'ngo', 'events', 'corporate'])
def test_non_sa_locale_applies_to_every_org_type(monkeypatch, org_type):
    """The country/language fix isn't limited to the type that had the
    coach-word bug — every default persona must respect org locale."""
    monkeypatch.setattr(
        FirebaseService, 'get_organisation',
        lambda org_id: _org(org_type, country='Kenya', supported_languages=['Swahili', 'English']),
    )

    prompt = ConversationService.get_ai_persona_prompt('org-1')

    assert 'Kenya' in prompt
    assert 'South Africa' not in prompt
    assert 'Swahili' in prompt


# ---------------------------------------------------------------------------
# FirebaseService.get_org_locale itself.
# ---------------------------------------------------------------------------

def test_get_org_locale_defaults_when_org_has_no_override(monkeypatch):
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org('sports'))

    locale = FirebaseService.get_org_locale('org-1')

    assert locale['country'] == FirebaseService.DEFAULT_COUNTRY
    assert locale['supported_languages'] == FirebaseService.DEFAULT_SUPPORTED_LANGUAGES


def test_get_org_locale_uses_org_override(monkeypatch):
    monkeypatch.setattr(
        FirebaseService, 'get_organisation',
        lambda org_id: _org('sports', country='Brazil', supported_languages=['Portuguese']),
    )

    locale = FirebaseService.get_org_locale('org-1')

    assert locale['country'] == 'Brazil'
    assert locale['supported_languages'] == ['Portuguese']


def test_get_org_locale_never_returns_the_literal_default_list(monkeypatch):
    """Same aliasing class as the DEFAULT_PRICING bug: the returned
    supported_languages list must be a copy, so a caller mutating it can
    never corrupt DEFAULT_SUPPORTED_LANGUAGES for every other org."""
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org('sports'))
    original = list(FirebaseService.DEFAULT_SUPPORTED_LANGUAGES)

    locale = FirebaseService.get_org_locale('org-1')
    locale['supported_languages'].append('Klingon')

    assert FirebaseService.DEFAULT_SUPPORTED_LANGUAGES == original


def test_get_org_locale_handles_missing_org_id():
    """org_id=None (the ultimate fallback path in get_ai_persona_prompt)
    must not raise — falls back to the SA defaults directly."""
    locale = FirebaseService.get_org_locale(None)

    assert locale['country'] == FirebaseService.DEFAULT_COUNTRY
    assert locale['supported_languages'] == FirebaseService.DEFAULT_SUPPORTED_LANGUAGES
