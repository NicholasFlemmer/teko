"""Regression guard for Phase 2 step 3d item 2: no hardcoded cricket-bat
emoji (used regardless of org type — e.g. shown to NGO orgs) anywhere in
the WhatsApp-facing message source files. Cheap, source-level check rather
than a behavioural test — this is the kind of thing that's trivial to
reintroduce in a future one-line copy edit, so it's worth a standing guard.

Usage:
    cd backend
    pytest tests/test_no_sport_specific_copy.py -v
"""
import os

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
