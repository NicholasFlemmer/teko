"""Role and org rules for creating, updating and deleting locations
(routes/locations.py).

Pins: coaches get 403 on create/update/delete and nothing is written;
location_admin and super_admin succeed; a new location is always stamped with
the caller's own organisation, whatever org_id the request body claims; a
caller with no organisation of their own cannot create one; update/delete
still cannot reach another organisation's location.

Pure unit tests: FirebaseService is stubbed via monkeypatch, so nothing here
touches Firestore. A minimal Flask app registers only locations_bp.

Usage:
    cd backend
    pytest tests/test_location_write_roles.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime, timedelta, timezone  # noqa: E402

import jwt as _jwt  # noqa: E402
import pytest  # noqa: E402
from flask import Flask  # noqa: E402

from config import Config  # noqa: E402
from routes.locations import locations_bp  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402

ORG_A = 'org-a'
ORG_B = 'org-b'
LOCATIONS = {'loc-a': {'id': 'loc-a', 'org_id': ORG_A, 'name': 'A Field'},
             'loc-b': {'id': 'loc-b', 'org_id': ORG_B, 'name': 'B Field'}}


def _headers(role, org_id=ORG_A):
    token = _jwt.encode(
        {'username': 'u', 'role': role, 'org_id': org_id,
         'exp': datetime.now(timezone.utc) + timedelta(hours=1)},
        Config.SECRET_KEY, algorithm='HS256')
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def env(monkeypatch):
    writes = {'created': [], 'updated': [], 'deleted': []}

    def create_location(data):
        writes['created'].append(dict(data))
        return {'id': 'new-loc', **data}

    def get_location(location_id, org_id):
        loc = LOCATIONS.get(location_id)
        return loc if loc and (org_id is None or loc['org_id'] == org_id) else None

    monkeypatch.setattr(FirebaseService, 'create_location', staticmethod(create_location))
    monkeypatch.setattr(FirebaseService, 'get_location', staticmethod(get_location))
    monkeypatch.setattr(FirebaseService, 'update_location', staticmethod(lambda lid, data: writes['updated'].append((lid, data)) or {'id': lid, **data}))
    monkeypatch.setattr(FirebaseService, 'delete_location', staticmethod(lambda lid: writes['deleted'].append(lid)))

    app = Flask(__name__)
    app.register_blueprint(locations_bp, url_prefix='/api/locations')
    app.testing = True
    return app.test_client(), writes


NEW_LOC = {'name': 'New Field', 'address': '1 Road'}


def test_coach_cannot_create_update_or_delete(env):
    client, writes = env
    assert client.post('/api/locations', json=NEW_LOC, headers=_headers('coach')).status_code == 403
    assert client.put('/api/locations/loc-a', json={'name': 'X'}, headers=_headers('coach')).status_code == 403
    assert client.delete('/api/locations/loc-a', headers=_headers('coach')).status_code == 403
    assert writes == {'created': [], 'updated': [], 'deleted': []}


@pytest.mark.parametrize('role', ['location_admin', 'super_admin'])
def test_admin_roles_can_create_update_delete(env, role):
    client, writes = env
    assert client.post('/api/locations', json=NEW_LOC, headers=_headers(role)).status_code == 201
    assert client.put('/api/locations/loc-a', json={'name': 'Renamed'}, headers=_headers(role)).status_code == 200
    assert client.delete('/api/locations/loc-a', headers=_headers(role)).status_code == 200
    assert len(writes['created']) == 1 and writes['updated'] == [('loc-a', {'name': 'Renamed'})] and writes['deleted'] == ['loc-a']


def test_new_location_is_always_in_the_callers_org_even_if_body_says_otherwise(env):
    client, writes = env
    r = client.post('/api/locations', json={**NEW_LOC, 'org_id': ORG_B}, headers=_headers('location_admin', ORG_A))
    assert r.status_code == 201
    assert writes['created'][0]['org_id'] == ORG_A


def test_caller_with_no_org_cannot_create_an_orphan_location(env):
    client, writes = env
    r = client.post('/api/locations', json=NEW_LOC, headers=_headers('super_admin', None))
    assert r.status_code == 403
    assert writes['created'] == []


def test_admin_cannot_update_or_delete_another_orgs_location(env):
    client, writes = env
    assert client.put('/api/locations/loc-b', json={'name': 'X'}, headers=_headers('location_admin', ORG_A)).status_code == 404
    assert client.delete('/api/locations/loc-b', headers=_headers('location_admin', ORG_A)).status_code == 404
    assert writes['updated'] == [] and writes['deleted'] == []


def test_all_roles_can_still_list_locations(env, monkeypatch):
    client, _ = env
    monkeypatch.setattr(FirebaseService, 'get_all_locations', staticmethod(lambda org_id: []))
    assert client.get('/api/locations', headers=_headers('coach')).status_code == 200
