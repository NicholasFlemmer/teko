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


def extract_coords_from_maps_url(url):
    """Extract lat/lng from a Google Maps URL, raw coord string, or shortened link.

    Handles:
        - Full Maps URLs with @lat,lng or ?q=lat,lng or /place/lat,lng
        - Raw coordinate strings like "-34.046864, 18.707249"
        - Shortened links (maps.app.goo.gl, share.google, etc.) by following redirects

    Returns:
        dict with latitude/longitude or None
    """
    if not url:
        return None

    text = url.strip()

    # Try extracting coords from the text directly (works for full URLs and raw coord strings)
    coords = _extract_coords_from_text(text)
    if coords:
        return coords

    # If it looks like a URL, resolve redirects and try again
    if text.startswith('http'):
        try:
            resp = requests.head(text, allow_redirects=True, timeout=5)
            resolved = resp.url
            if resolved != text:
                coords = _extract_coords_from_text(resolved)
                if coords:
                    return coords
        except Exception as e:
            logger.debug("Failed to resolve shortened URL %s: %s", text, e)

    return None


def _extract_coords_from_text(text):
    """Extract lat/lng from a string using known coordinate patterns.

    Returns:
        dict with latitude/longitude or None
    """
    # @lat,lng (standard Maps URL)
    m = re.search(r'@(-?\d+\.?\d*),(-?\d+\.?\d*)', text)
    if m:
        return {'latitude': float(m.group(1)), 'longitude': float(m.group(2))}
    # ?q=lat,lng
    m = re.search(r'[?&]q=(-?\d+\.?\d*),(-?\d+\.?\d*)', text)
    if m:
        return {'latitude': float(m.group(1)), 'longitude': float(m.group(2))}
    # /place/lat,lng or /search/lat,+lng (resolved shortened links)
    m = re.search(r'/(?:place|search)/(-?\d+\.?\d*),\+?(-?\d+\.?\d*)', text)
    if m:
        return {'latitude': float(m.group(1)), 'longitude': float(m.group(2))}
    # Raw coords: "-34.046864, 18.707249" (no URL structure)
    m = re.fullmatch(r'\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*', text)
    if m:
        lat, lng = float(m.group(1)), float(m.group(2))
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            return {'latitude': lat, 'longitude': lng}
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
