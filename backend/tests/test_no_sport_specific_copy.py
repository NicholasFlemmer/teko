"""Regression guard for Phase 2 step 3d item 2: no hardcoded cricket-bat
emoji (used regardless of org type — e.g. shown to NGO orgs) anywhere in
the WhatsApp-facing message source files. Cheap, source-level check rather
than a behavioural test — this is the kind of thing that's trivial to
reintroduce in a future one-line copy edit, so it's worth a standing guard.

Extended for Phase 2 step 3d item 3: the same class of bug (a hardcoded
sport-specific noun leaking into copy served to every org type) also
reintroduced "cricket" into the sports PARTICIPANT persona template
itself. That template is Python source text, not something a plain-string
scan over whole files can safely check (the module's own comments talk
*about* cricket as an example), so the second guard below imports the
template dict directly and checks per (org_type, person_type) entry.

Usage:
    cd backend
    pytest tests/test_no_sport_specific_copy.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.conversation_service import ConversationService  # noqa: E402

BACKEND_DIR = os.path.join(os.path.dirname(__file__), '..')

FILES_TO_CHECK = [
    'services/conversation_service.py',
    'services/scheduler_service.py',
]


def test_no_cricket_bat_emoji_in_whatsapp_message_sources():
    offenders = []
    for rel_path in FILES_TO_CHECK:
        path = os.path.join(BACKEND_DIR, rel_path)
        with open(path, encoding='utf-8') as f:
            for lineno, line in enumerate(f, start=1):
                if '🏏' in line:
                    offenders.append(f"{rel_path}:{lineno}: {line.strip()}")

    assert not offenders, (
        "Found 🏏 (cricket bat) in copy that isn't gated by org type — this emoji "
        "reads as sport-specific and gets served to NGO/events/corporate orgs too:\n"
        + "\n".join(offenders)
    )


# Sport/activity-specific nouns that must never appear in a persona template
# unless gated by org config — an org type of "sports" does not mean
# cricket specifically (could be football, netball, athletics, etc).
SPORT_SPECIFIC_NOUNS = [
    'cricket', 'batting', 'bowling', 'fielding', 'wicket', 'innings',
    'football', 'soccer', 'netball', 'rugby', 'basketball', 'athletics',
]

# The sports COACH persona's cricket-specific EXPERTISE section (batting/
# bowling/fielding) is a known, deliberate exception — whether it should
# stay cricket-specific is a product scope decision, not something this
# regression test enforces either way. Every other (org_type, person_type)
# combination, including the sports PARTICIPANT persona, must stay
# sport-neutral.
EXEMPT_FROM_SPORT_NOUN_CHECK = {('sports', 'coach')}


def test_no_hardcoded_sport_nouns_in_persona_templates():
    offenders = []
    for org_type, by_person_type in ConversationService.DEFAULT_AI_PERSONA_PROMPTS.items():
        for person_type, template in by_person_type.items():
            if (org_type, person_type) in EXEMPT_FROM_SPORT_NOUN_CHECK:
                continue
            lowered = template.lower()
            for noun in SPORT_SPECIFIC_NOUNS:
                if noun in lowered:
                    offenders.append(f"{org_type}/{person_type}: found '{noun}'")

    assert not offenders, (
        "Found hardcoded sport-specific nouns in persona templates not gated by "
        "org config (the sports coach persona's cricket expertise is a known, "
        "separately-tracked exception — see EXEMPT_FROM_SPORT_NOUN_CHECK):\n"
        + "\n".join(offenders)
    )
