"""Unit tests for assigning coaches to a team (routes/teams.py).

Pins: coach_ids on team create/update must name coaches that exist in the
team's own org; a coach from another org (or an unknown id) is rejected and
nothing is written; only super_admin / location_admin may set coach_ids; a
valid assignment is saved de-duplicated.

Pure unit tests: FirebaseService is stubbed via monkeypatch, so nothing here
touches Firestore. A minimal Flask app registers only teams_bp.

Usage:
    cd backend
    pytest tests/test_team_coach_assignment.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime, timedelta, timezone  # noqa: E402

import jwt as _jwt  # noqa: E402
import pytest  # noqa: E402
from flask import Flask  # noqa: E402

from config import Config  # noqa: E402
from routes.teams import teams_bp  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402

ORG_A = 'org-a'
ORG_B = 'org-b'
COACHES = {
    'coach-a1': {'id': 'coach-a1', 'org_id': ORG_A, 'name': 'A One'},
    'coach-a2': {'id': 'coach-a2', 'org_id': ORG_A, 'name': 'A Two'},
    'coach-b1': {'id': 'coach-b1', 'org_id': ORG_B, 'name': 'B One'},
}


def _headers(role='location_admin', org_id=ORG_A):
    token = _jwt.encode(
        {'username': 'u', 'role': role, 'org_id': org_id,
         'exp': datetime.now(timezone.utc) + timedelta(hours=1)},
        Config.SECRET_KEY, algorithm='HS256')
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def env(monkeypatch):
    writes = {'created': [], 'updated': []}
    team = {'id': 'team-1', 'name': 'T', 'age_group': 'U10', 'org_id': ORG_A, 'coach_ids': []}

    def get_coach(coach_id, org_id):
        c = COACHES.get(coach_id)
        return c if c and (org_id is None or c['org_id'] == org_id) else None

    def create_team(data):
        writes['created'].append(data)
        return {'id': 'new-team', **data}

    def update_team(team_id, data):
        writes['updated'].append((team_id, data))
        return {**team, **data}

    monkeypatch.setattr(FirebaseService, 'get_coach', staticmethod(get_coach))
    monkeypatch.setattr(FirebaseService, 'get_team', staticmethod(lambda tid, org_id: team if org_id in (None, ORG_A) and tid == 'team-1' else None))
    monkeypatch.setattr(FirebaseService, 'create_team', staticmethod(create_team))
    monkeypatch.setattr(FirebaseService, 'update_team', staticmethod(update_team))

    app = Flask(__name__)
    app.register_blueprint(teams_bp, url_prefix='/api/teams')
    app.testing = True
    return app.test_client(), writes


NEW_TEAM = {'name': 'T', 'age_group': 'U10'}


def test_create_rejects_coach_from_other_org(env):
    client, writes = env
    r = client.post('/api/teams', json={**NEW_TEAM, 'coach_ids': ['coach-a1', 'coach-b1']}, headers=_headers())
    assert r.status_code == 400
    assert writes['created'] == []


def test_create_rejects_unknown_coach(env):
    client, writes = env
    r = client.post('/api/teams', json={**NEW_TEAM, 'coach_ids': ['nope']}, headers=_headers())
    assert r.status_code == 400
    assert writes['created'] == []


def test_update_rejects_coach_from_other_org(env):
    client, writes = env
    r = client.put('/api/teams/team-1', json={'coach_ids': ['coach-b1']}, headers=_headers())
    assert r.status_code == 400
    assert writes['updated'] == []


def test_super_admin_update_still_checked_against_team_org(env):
    client, writes = env
    r = client.put('/api/teams/team-1', json={'coach_ids': ['coach-b1']}, headers=_headers('super_admin', None))
    assert r.status_code == 400
    assert writes['updated'] == []


def test_create_and_update_accept_same_org_coaches_deduplicated(env):
    client, writes = env
    r = client.post('/api/teams', json={**NEW_TEAM, 'coach_ids': ['coach-a1', 'coach-a1', 'coach-a2']}, headers=_headers())
    assert r.status_code == 201
    assert writes['created'][0]['coach_ids'] == ['coach-a1', 'coach-a2']
    r = client.put('/api/teams/team-1', json={'coach_ids': ['coach-a2']}, headers=_headers())
    assert r.status_code == 200
    assert writes['updated'] == [('team-1', {'coach_ids': ['coach-a2']})]


def test_clearing_coaches_is_allowed(env):
    client, writes = env
    r = client.put('/api/teams/team-1', json={'coach_ids': []}, headers=_headers())
    assert r.status_code == 200
    assert writes['updated'] == [('team-1', {'coach_ids': []})]


def test_malformed_coach_ids_rejected(env):
    client, writes = env
    for bad in ('coach-a1', [1, 2], [''], None):
        r = client.put('/api/teams/team-1', json={'coach_ids': bad}, headers=_headers())
        assert r.status_code == 400
    assert writes['updated'] == []


def test_coach_role_cannot_set_coach_ids_but_can_edit_other_fields(env):
    client, writes = env
    r = client.put('/api/teams/team-1', json={'coach_ids': ['coach-a1']}, headers=_headers('coach'))
    assert r.status_code == 403
    r = client.post('/api/teams', json={**NEW_TEAM, 'coach_ids': ['coach-a1']}, headers=_headers('coach'))
    assert r.status_code == 403
    assert writes['updated'] == [] and writes['created'] == []
    r = client.put('/api/teams/team-1', json={'name': 'Renamed'}, headers=_headers('coach'))
    assert r.status_code == 200
