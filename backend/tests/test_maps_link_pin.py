"""Tests for reading a venue pin from a Google Maps link.

The pin must be the link's place marker (!3d<lat>!4d<lng>), never the map
centre (@lat,lng) -- the centre is offset from the place by an amount that
grows as the map is zoomed out (about 250 m zoomed in, tens of km zoomed
out), which put 31 of 36 Sporting Chance venues west of the real spot.

Stand-ins only: requests.head (short-link lookup) and FirebaseService are
replaced, the real Maps service is never contacted. Link shapes below are
modelled on real Google Maps links, with made-up coordinates.

Usage:
    cd backend
    pytest tests/test_maps_link_pin.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest  # noqa: E402
from flask import Flask, g  # noqa: E402
from geopy.distance import geodesic  # noqa: E402

from routes import locations as loc_routes  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
from utils import geolocation  # noqa: E402
from utils.geolocation import extract_coords_from_maps_url, resolve_maps_link  # noqa: E402

MARKER = (-26.4228, 28.0789)

# Map centre (28.0000) and place marker (28.0789) differ by about 7.9 km: a
# map zoomed out to 12z.
ZOOMED_OUT = ("https://www.google.com/maps/place/Thabotona+Primary+School/@-26.4228,28.0000,12z/"
              "data=!3m1!4b1!4m6!3m5!1s0x1e9511:0xabc123!8m2!3d-26.4228!4d28.0789!16s%2Fg%2F11abc")
ZOOMED_IN = ("https://www.google.com/maps/place/Dr+Macken+Mistry/@-29.7972,30.9800,17z/"
             "data=!3m1!4b1!4m6!3m5!1s0x1ef7:0xdef456!8m2!3d-29.7972!4d30.9826!16s%2Fg%2F11def")
NO_MARKER = "https://www.google.com/maps/@-26.4228,28.0000,15z"
SHORT = "https://maps.app.goo.gl/cJQwhVoyqKbyFxB97"


class _Resp:
    def __init__(self, url, history=()):
        self.url = url
        self.history = list(history)


def _head_returns(monkeypatch, final_url, history=()):
    calls = []

    def fake_head(url, **kw):
        calls.append(url)
        return _Resp(final_url, [type('H', (), {'headers': {'Location': h}}) for h in history])
    monkeypatch.setattr(geolocation.requests, 'head', fake_head)
    return calls


def _no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError('network must not be used')
    monkeypatch.setattr(geolocation.requests, 'head', boom)


def _km(a, b):
    return geodesic(a, b).meters


# ── reading the link ─────────────────────────────────────────────────────

def test_zoomed_out_link_uses_marker_not_map_centre(monkeypatch):
    _no_network(monkeypatch)
    found = resolve_maps_link(ZOOMED_OUT)
    assert found['kind'] == 'marker'
    assert _km((found['latitude'], found['longitude']), MARKER) < 1
    # the old behaviour (map centre) would have been ~7.9 km away
    assert _km((-26.4228, 28.0000), MARKER) > 7000


def test_zoomed_in_link_uses_marker(monkeypatch):
    _no_network(monkeypatch)
    c = extract_coords_from_maps_url(ZOOMED_IN)
    assert _km((c['latitude'], c['longitude']), (-29.7972, 30.9826)) < 1


def test_link_with_no_marker_gives_no_pin_but_is_recognised_as_centre_only(monkeypatch):
    _no_network(monkeypatch)  # a full link with a point in it needs no lookup
    assert extract_coords_from_maps_url(NO_MARKER) is None
    assert resolve_maps_link(NO_MARKER)['kind'] == 'centre'


def test_short_link_is_followed_and_marker_used(monkeypatch):
    calls = _head_returns(monkeypatch, ZOOMED_OUT)
    c = extract_coords_from_maps_url(SHORT)
    assert calls == [SHORT]
    assert _km((c['latitude'], c['longitude']), MARKER) < 1


def test_short_link_that_lands_on_map_centre_only_gives_no_pin(monkeypatch):
    _head_returns(monkeypatch, NO_MARKER)
    assert extract_coords_from_maps_url(SHORT) is None
    assert resolve_maps_link(SHORT)['kind'] == 'centre'


def test_short_link_through_a_consent_page_is_still_read(monkeypatch):
    from urllib.parse import quote
    consent = 'https://consent.google.com/ml?continue=' + quote(ZOOMED_OUT, safe='') + '&gl=GB'
    _head_returns(monkeypatch, consent)
    c = extract_coords_from_maps_url(SHORT)
    assert _km((c['latitude'], c['longitude']), MARKER) < 1


def test_unreachable_short_link_gives_nothing_not_a_guess(monkeypatch):
    def down(*a, **k):
        raise geolocation.requests.ConnectionError('offline')
    monkeypatch.setattr(geolocation.requests, 'head', down)
    assert resolve_maps_link(SHORT) is None
    assert extract_coords_from_maps_url(SHORT) is None


@pytest.mark.parametrize('link,expected', [
    ('https://maps.google.com/?q=-34.046864,18.707249', (-34.046864, 18.707249)),
    ('https://www.google.com/maps/place/-34.046864,18.707249', (-34.046864, 18.707249)),
    ('https://www.google.com/maps/search/-34.046864,+18.707249', (-34.046864, 18.707249)),
    ('-34.046864, 18.707249', (-34.046864, 18.707249)),
])
def test_other_accepted_link_forms_still_work(monkeypatch, link, expected):
    _no_network(monkeypatch)
    c = extract_coords_from_maps_url(link)
    assert (c['latitude'], c['longitude']) == expected


def test_marker_wins_over_other_points_in_the_same_link(monkeypatch):
    _no_network(monkeypatch)
    link = ZOOMED_OUT + '&q=-1.0,1.0'
    assert _km(tuple(extract_coords_from_maps_url(link).values()), MARKER) < 1


# ── venue create / edit use it ───────────────────────────────────────────

@pytest.fixture
def env(monkeypatch):
    store = {'created': None, 'updated': None, 'existing': {}}
    monkeypatch.setattr(FirebaseService, 'create_location',
                        lambda data: store.update(created=dict(data)) or dict(data, id='loc-1'))
    monkeypatch.setattr(FirebaseService, 'get_location', lambda lid, org: dict(store['existing']) or None)
    monkeypatch.setattr(FirebaseService, 'update_location',
                        lambda lid, data: store.update(updated=dict(data)) or dict(data))
    return store


def _create(body):
    app = Flask(__name__)
    with app.test_request_context(json=body):
        g.current_user_org_id = 'org-a'; g.current_user_role = 'location_admin'
        res = loc_routes.create_location.__wrapped__({'id': 'u'})
        return res[1]


def _update(body):
    app = Flask(__name__)
    with app.test_request_context(json=body):
        g.current_user_org_id = 'org-a'; g.current_user_role = 'location_admin'
        return loc_routes.update_location.__wrapped__({'id': 'u'}, 'loc-1')[1]


def test_create_uses_marker_and_ignores_coordinates_sent_with_the_link(env, monkeypatch):
    _no_network(monkeypatch)
    assert _create({'name': 'V', 'google_maps_link': ZOOMED_OUT, 'latitude': -26.4228, 'longitude': 28.0000}) == 201
    c = env['created']
    assert _km((c['latitude'], c['longitude']), MARKER) < 1
    assert c['pin_needs_confirmation'] is False


def test_create_with_no_marker_saves_venue_without_pin_and_flags_it(env, monkeypatch):
    _no_network(monkeypatch)
    assert _create({'name': 'V', 'google_maps_link': NO_MARKER, 'latitude': -26.4228, 'longitude': 28.0000}) == 201
    c = env['created']
    assert 'latitude' not in c and 'longitude' not in c
    assert c['pin_needs_confirmation'] is True
    assert c['google_maps_link'] == NO_MARKER


def test_create_without_a_link_still_accepts_explicit_coordinates(env):
    assert _create({'name': 'V', 'latitude': -26.4, 'longitude': 28.0}) == 201
    assert env['created']['latitude'] == -26.4 and env['created']['pin_needs_confirmation'] is False


def test_edit_with_new_link_moves_pin_to_marker_and_clears_flag(env, monkeypatch):
    _no_network(monkeypatch)
    env['existing'] = {'id': 'loc-1', 'org_id': 'org-a', 'google_maps_link': 'old', 'latitude': -26.4228, 'longitude': 28.0, 'pin_needs_confirmation': True}
    assert _update({'google_maps_link': ZOOMED_OUT, 'latitude': -26.4228, 'longitude': 28.0}) == 200
    u = env['updated']
    assert _km((u['latitude'], u['longitude']), MARKER) < 1
    assert u['pin_needs_confirmation'] is False


def test_edit_with_no_marker_keeps_existing_pin_and_flags(env, monkeypatch):
    _no_network(monkeypatch)
    env['existing'] = {'id': 'loc-1', 'org_id': 'org-a', 'google_maps_link': 'old', 'latitude': -1.0, 'longitude': 1.0}
    assert _update({'google_maps_link': NO_MARKER, 'latitude': -26.4228, 'longitude': 28.0}) == 200
    u = env['updated']
    assert 'latitude' not in u and 'longitude' not in u  # existing pin untouched
    assert u['pin_needs_confirmation'] is True


def test_edit_unreachable_unchanged_trusted_link_leaves_flag_alone(env, monkeypatch):
    def down(*a, **k):
        raise geolocation.requests.ConnectionError('offline')
    monkeypatch.setattr(geolocation.requests, 'head', down)
    env['existing'] = {'id': 'loc-1', 'org_id': 'org-a', 'google_maps_link': SHORT, 'latitude': -26.4228, 'longitude': 28.0789}
    assert _update({'name': 'Renamed', 'google_maps_link': SHORT}) == 200
    assert 'pin_needs_confirmation' not in env['updated']
    assert 'latitude' not in env['updated']


def test_edit_without_link_or_coordinates_does_not_touch_the_pin(env):
    env['existing'] = {'id': 'loc-1', 'org_id': 'org-a', 'latitude': -26.4228, 'longitude': 28.0789}
    assert _update({'name': 'Renamed'}) == 200
    assert env['updated'] == {'name': 'Renamed'}


def test_a_client_cannot_set_the_flag_directly(env):
    env['existing'] = {'id': 'loc-1', 'org_id': 'org-a'}
    assert _update({'name': 'X', 'pin_needs_confirmation': False}) == 200
    assert 'pin_needs_confirmation' not in env['updated']


def test_radius_handling_is_unchanged(env, monkeypatch):
    _no_network(monkeypatch)
    assert _create({'name': 'V', 'google_maps_link': ZOOMED_OUT}) == 201
    assert env['created']['radius'] == 100
    env['existing'] = {'id': 'loc-1', 'org_id': 'org-a'}
    assert _update({'radius': 150}) == 200
    assert env['updated']['radius'] == 150
