"""Unit tests for POST /api/locations/geocode (routes/locations.py).

Moves geocoding server-side so the Google Maps API key never has to sit in
the public frontend bundle for a web-service (REST) call -- see
frontend/src/lib/geocode.ts, which now calls this endpoint instead of
maps.googleapis.com directly.

Covers:
  1. No token at all -> 401, same token_required gate every other
     locations endpoint uses.
  2. A valid, org-scoped token -> 200 with latitude/longitude, and proves
     the route actually calls utils.geolocation.geocode_address() (not a
     reimplementation) by asserting on the address it was passed.
  3. geocode_address() returning None (address doesn't resolve) -> 404.
  4. A token with no resolvable org context -> 403, the same
     _resolve_org_scope() gate every other locations endpoint runs first --
     this is what "org-scoped the same way as neighbouring endpoints"
     means for an endpoint with no per-org resource of its own to isolate.

Pure unit tests: routes.locations.geocode_address and .is_rate_limited are
both monkeypatched, so nothing here touches Firestore or the real Google
API. A minimal Flask app registers only locations_bp, same convention as
test_token_org_id_scoping.py / test_org_id_auth_wiring.py.

Usage:
    cd backend
    pytest tests/test_locations_geocode.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) now lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

from datetime import datetime, timedelta, timezone  # noqa: E402

import jwt as _jwt  # noqa: E402
import pytest  # noqa: E402
from flask import Flask  # noqa: E402

from config import Config  # noqa: E402
import routes.locations as locations_module  # noqa: E402
from routes.locations import locations_bp  # noqa: E402


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(locations_bp, url_prefix='/api/locations')
    app.testing = True
    return app.test_client()


def _make_token(role='location_admin', org_id='org-a', username='admin@example.com'):
    payload = {
        'username': username,
        'role': role,
        'org_id': org_id,
        'exp': datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return _jwt.encode(payload, Config.SECRET_KEY, algorithm='HS256')


def _auth_header(token):
    return {'Authorization': f'Bearer {token}'}


def _allow_rate_limit(monkeypatch):
    monkeypatch.setattr(locations_module, 'is_rate_limited', lambda key, max_count, window_seconds: False)


# ---------------------------------------------------------------------------
# 1. No token -> 401.
# ---------------------------------------------------------------------------

def test_unauthenticated_request_rejected(client):
    resp = client.post('/api/locations/geocode', json={'address': '1 Infinite Loop'})

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 2. Authenticated, org-scoped request -> 200 with coordinates, via the
#    real geocode_address() import (not a duplicated implementation).
# ---------------------------------------------------------------------------

def test_authenticated_request_returns_coordinates(client, monkeypatch):
    _allow_rate_limit(monkeypatch)
    captured = {}

    def _fake_geocode_address(address):
        captured['address'] = address
        return {'latitude': -33.918, 'longitude': 18.423}

    monkeypatch.setattr(locations_module, 'geocode_address', _fake_geocode_address)

    token = _make_token()
    resp = client.post('/api/locations/geocode', json={'address': '1 Infinite Loop'}, headers=_auth_header(token))

    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True
    assert body['latitude'] == -33.918
    assert body['longitude'] == 18.423
    assert captured['address'] == '1 Infinite Loop'


# ---------------------------------------------------------------------------
# 3. geocode_address() finds nothing -> 404, not a 200 with null coords.
# ---------------------------------------------------------------------------

def test_address_that_does_not_geocode_returns_404(client, monkeypatch):
    _allow_rate_limit(monkeypatch)
    monkeypatch.setattr(locations_module, 'geocode_address', lambda address: None)

    token = _make_token()
    resp = client.post('/api/locations/geocode', json={'address': 'not a real place at all'}, headers=_auth_header(token))

    assert resp.status_code == 404
    assert resp.get_json()['success'] is False


# ---------------------------------------------------------------------------
# 4. A token with no resolvable org context is rejected before geocoding
#    ever runs -- same _resolve_org_scope() gate as every sibling endpoint,
#    so this can't be used as an open geocoding proxy by a token that
#    isn't legitimately scoped to an org.
# ---------------------------------------------------------------------------

def test_token_with_no_org_context_rejected(client, monkeypatch):
    calls = []
    monkeypatch.setattr(locations_module, 'geocode_address', lambda address: calls.append(address) or {'latitude': 1.0, 'longitude': 2.0})
    monkeypatch.setattr(locations_module, 'is_rate_limited', lambda key, max_count, window_seconds: (_ for _ in ()).throw(AssertionError("must not reach rate limiting")))

    token = _make_token(role='location_admin', org_id=None)
    resp = client.post('/api/locations/geocode', json={'address': '1 Infinite Loop'}, headers=_auth_header(token))

    assert resp.status_code == 403
    assert calls == [], "geocode_address must never be called for a token with no org context"
