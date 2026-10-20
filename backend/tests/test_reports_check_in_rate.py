"""Reports check-in rate: only sessions that have already started (org
timezone) and are not cancelled count; checked-in sessions are split into
verified / unverified; the headcount total feeds the 'participants' tile.

Run:
    cd backend
    pytest tests/test_reports_check_in_rate.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime, timedelta, timezone  # noqa: E402

import jwt as _jwt  # noqa: E402
import pytest  # noqa: E402
from flask import Flask  # noqa: E402

from config import Config  # noqa: E402
from routes.reports import reports_bp  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402

ORG = 'org-a'
NOW = datetime(2026, 10, 20, 12, 0)  # org-local wall clock


def _s(sid, date, start, status, coach='c1', loc='l1', verified=None, headcount=None, coach_check_ins=None):
    d = {'id': sid, 'date': date, 'start_time': start, 'status': status,
         'coach_ids': [coach], 'location_id': loc}
    if verified is not None:
        d['location_verified'] = verified
    if headcount is not None:
        d['headcount'] = {'total': headcount}
    if coach_check_ins is not None:
        d['coach_check_ins'] = coach_check_ins
    return d


SESSIONS = [
    _s('1', '2026-10-19', '09:00', 'checked_in', verified=True),
    _s('2', '2026-10-19', '10:00', 'checked_in', verified=False),
    _s('3', '2026-10-19', '11:00', 'completed', verified=True),
    _s('4', '2026-10-19', '12:00', 'missed'),
    _s('5', '2026-10-20', '11:00', 'checked_in', verified=False),   # today, already started
    _s('6', '2026-10-20', '15:30', 'scheduled'),                    # today, not started
    _s('7', '2026-10-25', '09:00', 'scheduled'),                    # future
    _s('8', '2026-10-18', '09:00', 'cancelled'),                    # cancelled
]


@pytest.fixture
def client(monkeypatch, request):
    sessions = getattr(request, 'param', SESSIONS)
    org = {'id': ORG, 'timezone': 'Africa/Johannesburg', 'attendance_mode': 'named'}
    app = Flask(__name__)
    app.register_blueprint(reports_bp, url_prefix='/api/reports')
    app.testing = True
    monkeypatch.setattr(FirebaseService, 'get_org_now', classmethod(lambda cls, org_id: NOW))
    monkeypatch.setattr(FirebaseService, 'get_all_sessions', classmethod(lambda cls, org_id, **kw: list(sessions)))
    monkeypatch.setattr(FirebaseService, 'get_sessions_by_date_range', classmethod(lambda cls, o, a, b: list(sessions)))
    monkeypatch.setattr(FirebaseService, 'get_organisation', classmethod(lambda cls, org_id: org))
    monkeypatch.setattr(FirebaseService, 'get_all_coaches', classmethod(lambda cls, org_id: [{'id': 'c1', 'name': 'Coach One'}]))
    monkeypatch.setattr(FirebaseService, 'get_all_locations', classmethod(lambda cls, org_id: [{'id': 'l1', 'name': 'Venue One'}]))
    monkeypatch.setattr(FirebaseService, 'count_players', classmethod(lambda cls, org_id: 30))
    monkeypatch.setattr(FirebaseService, 'count_active_coaches', classmethod(lambda cls, org_id: 2))
    client = app.test_client()
    client.org = org
    return client


def _hdr():
    tok = _jwt.encode({'username': 'u', 'role': 'location_admin', 'org_id': ORG,
                       'exp': datetime.now(timezone.utc) + timedelta(hours=1)},
                      Config.SECRET_KEY, algorithm='HS256')
    return {'Authorization': f'Bearer {tok}'}


def test_stats_count_only_started_non_cancelled_sessions(client):
    st = client.get('/api/reports/stats', headers=_hdr()).get_json()['stats']
    # started + not cancelled: sessions 1-5 (6 and 7 are future, 8 cancelled)
    assert st['total_sessions'] == 5
    assert st['checked_in'] == 4
    assert st['check_in_rate'] == 80   # 4/5, not 4/8 or 4/7


def test_stats_split_verified_and_unverified(client):
    st = client.get('/api/reports/stats', headers=_hdr()).get_json()['stats']
    assert st['verified_check_ins'] == 2
    assert st['unverified_check_ins'] == 2
    assert st['verified_check_ins'] + st['unverified_check_ins'] == st['checked_in']


def test_coach_and_venue_rows_share_the_same_rate_and_split(client):
    coach = client.get('/api/reports/coach-attendance', headers=_hdr()).get_json()['data'][0]
    venue = client.get('/api/reports/location-attendance', headers=_hdr()).get_json()['data'][0]
    for row in (coach, venue):
        assert row['total_sessions'] == 5
        assert row['checked_in'] == 4
        assert row['verified_check_ins'] == 2
        assert row['unverified_check_ins'] == 2


def test_coach_row_uses_that_coachs_own_check_in_verification(monkeypatch, client):
    sessions = [_s('1', '2026-10-19', '09:00', 'checked_in', verified=True,
                   coach_check_ins={'c1': {'location_verified': False}})]
    monkeypatch.setattr(FirebaseService, 'get_sessions_by_date_range', classmethod(lambda cls, o, a, b: sessions))
    row = client.get('/api/reports/coach-attendance?start_date=2026-10-01&end_date=2026-10-31',
                     headers=_hdr()).get_json()['data'][0]
    assert (row['verified_check_ins'], row['unverified_check_ins']) == (0, 1)


def test_headcount_org_total_is_summed_across_range(monkeypatch, client):
    client.org['attendance_mode'] = 'headcount'
    sessions = [
        _s('1', '2026-10-19', '09:00', 'checked_in', headcount=20),
        _s('2', '2026-10-20', '09:00', 'checked_in', headcount=17),
        _s('3', '2026-10-20', '10:00', 'missed'),
        _s('4', '2026-10-18', '10:00', 'cancelled', headcount=99),   # cancelled: ignored
    ]
    monkeypatch.setattr(FirebaseService, 'get_sessions_by_date_range', classmethod(lambda cls, o, a, b: sessions))
    st = client.get('/api/reports/stats?start_date=2026-10-01&end_date=2026-10-31',
                    headers=_hdr()).get_json()['stats']
    assert st['attendance_mode'] == 'headcount'
    assert st['total_headcount'] == 37
    assert st['total_students'] == 30   # enrolled count still returned unchanged


def test_named_org_reports_named_mode(client):
    st = client.get('/api/reports/stats', headers=_hdr()).get_json()['stats']
    assert st['attendance_mode'] == 'named'
    assert st['total_students'] == 30


def test_no_sessions_started_gives_zero_rate_not_an_error(monkeypatch, client):
    monkeypatch.setattr(FirebaseService, 'get_all_sessions',
                        classmethod(lambda cls, org_id, **kw: [_s('7', '2026-10-25', '09:00', 'scheduled')]))
    st = client.get('/api/reports/stats', headers=_hdr()).get_json()['stats']
    assert (st['total_sessions'], st['check_in_rate']) == (0, 0)
