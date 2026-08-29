"""Unit tests for org-timezone-aware date/time resolution (correctness
defect: session date/start_time were computed from the Cloud Run container
clock, which runs UTC -- wrong by 2h for CATCH Trust (Africa/Johannesburg)
and crossing the UTC date boundary entirely for Cricket without Boundaries
Brazil (America/Sao_Paulo)).

Covers:
  - FirebaseService.get_org_now: correct offset for two real IANA zones,
    the UTC-midnight-crossing case, no-timezone-configured fallback (with
    WARNING), invalid-timezone fallback (with WARNING, no raise), and two
    orgs resolving independently in the same process.
  - The fix wired into the real code paths: ConversationService.
    _create_on_demand_session (the /session handler's date/start_time) and
    handle_location_check_in (today's-session date matching), proving the
    Sao Paulo midnight-crossing session a coach starts at 21:00 local is
    still found by a check-in five minutes later, same local day.

"Now" is frozen by monkeypatching the `datetime` name inside
services.firebase_service to a datetime subclass whose .now(tz) is pinned
to a fixed real UTC instant -- get_org_now's own arithmetic (tz-aware
conversion, .replace(tzinfo=None)) runs for real against that frozen
instant, so this exercises the actual zoneinfo conversion, not a mocked
result.

Pure unit tests: FirebaseService.get_organisation/get_all_sessions/
get_all_teams/create_session and PersonService/WhatsAppService are all
stubbed via monkeypatch, so nothing here touches real infrastructure --
same convention as test_start_session.py and test_gps_checkin_org_scoping.py.

Usage:
    cd backend
    pytest tests/test_org_timezone.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) now lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

from datetime import datetime as real_datetime, timezone as dt_timezone  # noqa: E402

import pytest  # noqa: E402
import services.firebase_service as fs_module  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from services.person_service import PersonService  # noqa: E402
from services.whatsapp_service import WhatsAppService  # noqa: E402


class _FrozenDateTime(real_datetime):
    """A datetime subclass whose .now(tz) is pinned to a fixed real UTC
    instant, set per-test via _freeze(). Everything else (arithmetic,
    strftime, astimezone) is the real datetime implementation -- only
    "what time is it right now" is controlled."""
    _frozen_utc = None

    @classmethod
    def now(cls, tz=None):
        instant = cls._frozen_utc
        if instant is None:
            raise RuntimeError("_FrozenDateTime used without freezing an instant first")
        if tz is None:
            return instant.replace(tzinfo=None)
        return instant.astimezone(tz)


@pytest.fixture
def freeze_now(monkeypatch):
    """Freeze services.firebase_service's clock to a specific real UTC
    instant. Returns a function taking (year, month, day, hour, minute)."""
    monkeypatch.setattr(fs_module, 'datetime', _FrozenDateTime)

    def _freeze(year, month, day, hour, minute, second=0):
        _FrozenDateTime._frozen_utc = real_datetime(year, month, day, hour, minute, second, tzinfo=dt_timezone.utc)

    yield _freeze
    _FrozenDateTime._frozen_utc = None


def _org(timezone_value):
    return {'id': 'org-x', 'timezone': timezone_value}


# ---------------------------------------------------------------------------
# FirebaseService.get_org_now -- direct unit tests
# ---------------------------------------------------------------------------

def test_africa_johannesburg_is_two_hours_ahead_of_utc(monkeypatch, freeze_now):
    freeze_now(2026, 3, 11, 10, 0)  # 10:00 UTC
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org('Africa/Johannesburg'))

    now = FirebaseService.get_org_now('org-x')

    assert now == real_datetime(2026, 3, 11, 12, 0)  # 10:00 UTC + 2h


def test_america_sao_paulo_is_three_hours_behind_utc(monkeypatch, freeze_now):
    freeze_now(2026, 3, 11, 10, 0)  # 10:00 UTC
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org('America/Sao_Paulo'))

    now = FirebaseService.get_org_now('org-x')

    assert now == real_datetime(2026, 3, 11, 7, 0)  # 10:00 UTC - 3h


def test_sao_paulo_21h00_is_still_the_previous_utc_calendar_date(monkeypatch, freeze_now):
    """The exact bug scenario: an evening session in Brazil crosses
    midnight UTC. 00:05 UTC on the 11th is 21:05 on the 10th in Sao Paulo
    -- get_org_now must report the 10th, not the UTC-rolled-over 11th."""
    freeze_now(2026, 3, 11, 0, 5)  # just past midnight UTC
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org('America/Sao_Paulo'))

    now = FirebaseService.get_org_now('org-x')

    assert now.strftime('%Y-%m-%d') == '2026-03-10'
    assert now.strftime('%H:%M') == '21:05'


def test_no_timezone_configured_falls_back_to_utc_and_logs_warning(monkeypatch, freeze_now, caplog):
    freeze_now(2026, 3, 11, 10, 0)
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: {'id': org_id})  # no 'timezone' key

    with caplog.at_level('WARNING'):
        now = FirebaseService.get_org_now('org-unconfigured')

    assert now == real_datetime(2026, 3, 11, 10, 0)  # UTC, unshifted
    assert any(
        r.levelname == 'WARNING' and 'org-unconfigured' in r.message
        for r in caplog.records
    )


def test_invalid_timezone_falls_back_to_utc_logs_warning_does_not_raise(monkeypatch, freeze_now, caplog):
    freeze_now(2026, 3, 11, 10, 0)
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org('Not/ARealZone'))

    with caplog.at_level('WARNING'):
        now = FirebaseService.get_org_now('org-bad-tz')  # must not raise

    assert now == real_datetime(2026, 3, 11, 10, 0)  # UTC, unshifted
    assert any(
        r.levelname == 'WARNING' and 'org-bad-tz' in r.message and 'Not/ARealZone' in r.message
        for r in caplog.records
    )


def test_two_orgs_in_different_timezones_resolve_independently_same_process(monkeypatch, freeze_now):
    freeze_now(2026, 3, 11, 10, 0)  # single fixed instant for both calls
    orgs = {
        'org-a': _org('Africa/Johannesburg'),
        'org-b': _org('America/Sao_Paulo'),
    }
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: orgs[org_id])

    now_a = FirebaseService.get_org_now('org-a')
    now_b = FirebaseService.get_org_now('org-b')

    assert now_a == real_datetime(2026, 3, 11, 12, 0)  # +2h
    assert now_b == real_datetime(2026, 3, 11, 7, 0)   # -3h
    assert (now_a - now_b).total_seconds() == 5 * 3600  # 5h apart, as expected


# ---------------------------------------------------------------------------
# Wired into the real /session handler: start_time and date reflect the
# org's own timezone, not the container clock.
# ---------------------------------------------------------------------------

def _coach(org_id, coach_id='coach-1', phone='27821234567'):
    return {'id': coach_id, 'org_id': org_id, 'name': 'Alex', 'phone_number': phone, 'person_type': 'coach'}


def test_start_session_start_time_is_two_hours_ahead_of_utc_for_johannesburg_org(monkeypatch, freeze_now):
    freeze_now(2026, 3, 11, 10, 0)  # 10:00 UTC
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org('Africa/Johannesburg'))
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [])
    monkeypatch.setattr(FirebaseService, 'get_all_teams', lambda org_id, location_id=None: [
        {'id': 'team-1', 'name': 'U12s', 'coach_ids': ['coach-1']},
    ])
    created = {}
    monkeypatch.setattr(FirebaseService, 'create_session', lambda data: created.update(data) or {'id': 'sess-1', **data})

    ConversationService.handle_start_session_command(_coach('org-x'))

    assert created['start_time'] == '12:00'  # 10:00 UTC + 2h
    assert created['date'] == '2026-03-11'


def test_start_session_records_sao_paulo_date_not_the_following_utc_date(monkeypatch, freeze_now):
    """The concrete version of the bug: a coach in Brazil sends /session at
    21:00 local, which is already past midnight in UTC -- the created
    session must carry the Sao Paulo date, not the UTC date one day ahead."""
    freeze_now(2026, 3, 11, 0, 0)  # 00:00 UTC == 21:00 Sao Paulo on the 10th
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org('America/Sao_Paulo'))
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [])
    monkeypatch.setattr(FirebaseService, 'get_all_teams', lambda org_id, location_id=None: [
        {'id': 'team-1', 'name': 'Sub-15', 'coach_ids': ['coach-1']},
    ])
    created = {}
    monkeypatch.setattr(FirebaseService, 'create_session', lambda data: created.update(data) or {'id': 'sess-1', **data})

    ConversationService.handle_start_session_command(_coach('org-brazil'))

    assert created['start_time'] == '21:00'
    assert created['date'] == '2026-03-10'  # Sao Paulo's date, not UTC's 2026-03-11


# ---------------------------------------------------------------------------
# Wired into the real check-in flow: date matching uses the org's timezone.
# ---------------------------------------------------------------------------

def test_checkin_finds_a_sao_paulo_2100_session_from_a_2105_checkin_same_local_day(monkeypatch, freeze_now):
    """A session created at 21:00 Sao Paulo (date '2026-03-10') must still
    be found by a check-in five minutes later at 21:05 Sao Paulo, even
    though the real-world UTC calendar date has already rolled over to
    2026-03-11 in between."""
    freeze_now(2026, 3, 11, 0, 5)  # 00:05 UTC == 21:05 Sao Paulo, still the 10th locally
    monkeypatch.setattr(FirebaseService, 'get_organisation', lambda org_id: _org('America/Sao_Paulo'))

    coach = _coach('org-brazil', coach_id='coach-9', phone='5511987654321')
    monkeypatch.setattr(PersonService, 'resolve', lambda phone: dict(coach))

    session = {
        'id': 'sess-brazil-1',
        'date': '2026-03-10',  # stored using the org's own local date at creation
        'status': 'scheduled',
        'coach_id': 'coach-9',
        'coach_ids': ['coach-9'],
    }
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', lambda org_id, coach_id=None, **kw: [dict(session)])

    check_in_calls = []
    monkeypatch.setattr(FirebaseService, 'check_in_session',
                         lambda session_id, data, org_id, coach_id=None: check_in_calls.append(session_id) or dict(session))

    sent = {}
    monkeypatch.setattr(WhatsAppService, 'send_message',
                         lambda phone_number, message_text: sent.update(message_text=message_text) or {'success': True})

    ConversationService.handle_location_check_in('+5511987654321', -23.55, -46.63)

    # The session was found and checked into -- not the "no session
    # scheduled for today" refusal, which is exactly what a UTC-only date
    # comparison would have produced here (UTC date is already the 11th).
    assert check_in_calls == ['sess-brazil-1']
    assert "don't have a session scheduled" not in (sent.get('message_text') or '')
