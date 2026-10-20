import re
import logging
import requests
from geopy.distance import geodesic
from config import Config

logger = logging.getLogger(__name__)

def calculate_distance(location1, location2):
    """Calculate distance between two coordinates in meters
    
    Args:
        location1: dict with 'latitude' and 'longitude' keys
        location2: dict with 'latitude' and 'longitude' keys
        
    Returns:
        float: Distance in meters
    """
    if not location1 or not location2:
        return None
    
    coords1 = (location1.get('latitude'), location1.get('longitude'))
    coords2 = (location2.get('latitude'), location2.get('longitude'))
    
    if None in coords1 or None in coords2:
        return None
    
    distance = geodesic(coords1, coords2).meters
    return distance

def verify_location(actual_location, expected_location, radius_meters=None):
    """Verify if actual location is within acceptable radius of expected location
    
    Args:
        actual_location: dict with 'latitude' and 'longitude' keys
        expected_location: dict with 'latitude' and 'longitude' keys
        radius_meters: acceptable radius in meters (defaults to Config.GEOLOCATION_RADIUS_METERS)
        
    Returns:
        dict: {
            'verified': bool,
            'distance': float (meters),
            'within_radius': bool
        }
    """
    if radius_meters is None:
        radius_meters = Config.GEOLOCATION_RADIUS_METERS
    
    distance = calculate_distance(actual_location, expected_location)
    
    if distance is None:
        return {
            'verified': False,
            'distance': None,
            'within_radius': False,
            'error': 'Invalid location data'
        }
    
    within_radius = distance <= radius_meters
    
    return {
        'verified': True,
        'distance': distance,
        'within_radius': within_radius,
        'allowed_radius': radius_meters
    }

def format_location(latitude, longitude):
    """Format location coordinates

    Args:
        latitude: float
        longitude: float

    Returns:
        dict: Formatted location
    """
    return {
        'latitude': float(latitude),
        'longitude': float(longitude)
    }


# How trustworthy a point read from a Google Maps link is, best first.
#   marker -- the place marker (!3d<lat>!4d<lng>) inside a place link
#   point  -- an explicit point in the link: ?q=lat,lng or /place|search/lat,lng
#   raw    -- the link text is just "lat, lng"
#   centre -- only the map's centre (@lat,lng): NOT the place -- how far it is
#             from the real place depends on how far the map was zoomed out
#             (about 250 m zoomed in, many km zoomed out), so it is never
#             used as a venue pin.
_KIND_RANK = {'marker': 0, 'point': 1, 'raw': 2, 'centre': 3}
PIN_KINDS = ('marker', 'point', 'raw')
_SHORT_LINK_HOSTS = ('maps.app.goo.gl', 'goo.gl', 'g.co', 'share.google')


def _extract_point_from_text(text):
    """Best point found in a string, as
    {'latitude', 'longitude', 'kind'} (see _KIND_RANK), or None."""
    # The place marker. A place link can carry several !3d!4d pairs (e.g.
    # directions); the marker of the place is the last one.
    markers = re.findall(r'!3d(-?\d+\.?\d*)!4d(-?\d+\.?\d*)', text)
    if markers:
        return {'latitude': float(markers[-1][0]), 'longitude': float(markers[-1][1]), 'kind': 'marker'}
    # ?q=lat,lng
    m = re.search(r'[?&]q=(-?\d+\.?\d*),(-?\d+\.?\d*)', text)
    if m:
        return {'latitude': float(m.group(1)), 'longitude': float(m.group(2)), 'kind': 'point'}
    # /place/lat,lng or /search/lat,+lng (resolved shortened links)
    m = re.search(r'/(?:place|search)/(-?\d+\.?\d*),\+?(-?\d+\.?\d*)', text)
    if m:
        return {'latitude': float(m.group(1)), 'longitude': float(m.group(2)), 'kind': 'point'}
    # Raw coords: "-34.046864, 18.707249" (no URL structure)
    m = re.fullmatch(r'\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*', text)
    if m:
        lat, lng = float(m.group(1)), float(m.group(2))
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            return {'latitude': lat, 'longitude': lng, 'kind': 'raw'}
    # @lat,lng -- the map centre, not the place
    m = re.search(r'@(-?\d+\.?\d*),(-?\d+\.?\d*)', text)
    if m:
        return {'latitude': float(m.group(1)), 'longitude': float(m.group(2)), 'kind': 'centre'}
    return None


def _best(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return a if _KIND_RANK[a['kind']] <= _KIND_RANK[b['kind']] else b


def resolve_maps_link(url):
    """Read a point from a Google Maps link, as
    {'latitude', 'longitude', 'kind'} or None if nothing could be read.

    Handles full links, raw "lat, lng" text and shortened links
    (maps.app.goo.gl etc., by following redirects -- needs network access;
    on failure the result is None, never a guess). Look at 'kind': only
    'marker', 'point' and 'raw' are a real place -- see _KIND_RANK.
    """
    if not url:
        return None
    text = url.strip()
    found = _extract_point_from_text(text)
    if found and found['kind'] in PIN_KINDS:
        return found

    host = re.sub(r'^https?://', '', text).split('/')[0].lower() if text.startswith('http') else ''
    # Only follow redirects when they can tell us more: a short link, or a
    # link with no point in it at all.
    if text.startswith('http') and (found is None or host in _SHORT_LINK_HOSTS):
        try:
            resp = requests.head(text, allow_redirects=True, timeout=5)
            from urllib.parse import unquote, urlparse, parse_qs
            candidates = [r.headers.get('Location', '') for r in resp.history] + [resp.url]
            for c in list(candidates):
                # Consent / interstitial pages carry the real link in ?continue=
                for v in parse_qs(urlparse(c).query).get('continue', []):
                    candidates.append(unquote(v))
            for c in candidates:
                found = _best(found, _extract_point_from_text(c) if c else None)
        except Exception as e:
            logger.debug("Failed to resolve shortened URL %s: %s", text, e)
    return found


def extract_coords_from_maps_url(url):
    """Venue-pin coordinates from a Google Maps link: {'latitude', 'longitude'}
    or None. Only a real place point counts (place marker, explicit point,
    raw coordinates). A link with just a map centre gives None -- use
    resolve_maps_link() to tell "no marker" from "couldn't read the link"."""
    found = resolve_maps_link(url)
    if found and found['kind'] in PIN_KINDS:
        return {'latitude': found['latitude'], 'longitude': found['longitude']}
    return None


def geocode_address(address):
    """Geocode an address using Google Maps Geocoding API.

    Returns:
        dict with latitude/longitude or None
    """
    api_key = Config.GOOGLE_MAPS_API_KEY
    if not api_key or not address or not address.strip():
        return None
    try:
        resp = requests.get(
            'https://maps.googleapis.com/maps/api/geocode/json',
            params={'address': address, 'key': api_key},
            timeout=5
        )
        data = resp.json()
        if data.get('status') == 'OK':
            results = data.get('results')
            if results and isinstance(results, list) and len(results) > 0:
                geometry = results[0].get('geometry', {})
                loc = geometry.get('location', {})
                lat = loc.get('lat')
                lng = loc.get('lng')
                if lat is not None and lng is not None:
                    return {'latitude': lat, 'longitude': lng}
        elif data.get('status') != 'ZERO_RESULTS':
            logger.warning(f"Geocoding returned status '{data.get('status')}' for '{address}'")
    except Exception as e:
        logger.warning(f"Geocoding failed for '{address}': {e}")
    return None
