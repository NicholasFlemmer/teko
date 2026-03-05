import re
import requests
from geopy.distance import geodesic
from config import Config

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
    """Extract lat/lng from a Google Maps URL.

    Returns:
        dict with latitude/longitude or None
    """
    if not url:
        return None
    # @lat,lng
    m = re.search(r'@(-?\d+\.?\d*),(-?\d+\.?\d*)', url)
    if m:
        return {'latitude': float(m.group(1)), 'longitude': float(m.group(2))}
    # ?q=lat,lng
    m = re.search(r'[?&]q=(-?\d+\.?\d*),(-?\d+\.?\d*)', url)
    if m:
        return {'latitude': float(m.group(1)), 'longitude': float(m.group(2))}
    # /place/lat,lng
    m = re.search(r'/place/(-?\d+\.?\d*),(-?\d+\.?\d*)', url)
    if m:
        return {'latitude': float(m.group(1)), 'longitude': float(m.group(2))}
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
        if data.get('status') == 'OK' and data.get('results'):
            loc = data['results'][0]['geometry']['location']
            return {'latitude': loc['lat'], 'longitude': loc['lng']}
    except Exception as e:
        print(f"⚠️ Geocoding failed for '{address}': {e}")
    return None
