import logging
from flask import Blueprint, request, jsonify, g
from config import Config
from services.firebase_service import FirebaseService
from services.rate_limiter import is_rate_limited
from routes.auth import token_required, role_required
from utils.geolocation import resolve_maps_link, geocode_address, PIN_KINDS
from utils.request_ip import get_trusted_client_ip

logger = logging.getLogger(__name__)

locations_bp = Blueprint('locations', __name__)

# Proxies a paid, per-request Google API call, so this needs its own limit
# rather than riding on general request throughput. Keyed by the caller
# (current_user) the same way invite() in routes/auth.py rate-limits an
# authenticated action, plus IP as a second key for the same
# shared-office-network reasoning used there -- either one tripping blocks
# the request. 20/5min per user comfortably covers filling in several
# locations in one sitting; 40/5min per IP is looser, same reasoning as
# the other per-IP limits in routes/auth.py.
GEOCODE_USER_RATE_LIMIT = (20, 5 * 60)
GEOCODE_IP_RATE_LIMIT = (40, 5 * 60)


def _resolve_org_scope():
    """Resolve the org_id to filter by for the current request.

    Returns (org_id, None) on success, or (None, error_response) if the
    caller has no org context and isn't the intentional super_admin
    cross-org case (role == 'super_admin' with no assigned org).
    """
    org_id = getattr(g, 'current_user_org_id', None)
    role = getattr(g, 'current_user_role', None)
    if org_id is None and role != 'super_admin':
        return None, (jsonify({'success': False, 'error': 'Organisation context missing'}), 403)
    return org_id, None


@locations_bp.route('', methods=['GET'])
@token_required
def get_locations(current_user):
    """Get all locations"""
    try:
        org_id, err = _resolve_org_scope()
        if err:
            return err
        locations = FirebaseService.get_all_locations(org_id)
        return jsonify({
            'success': True,
            'locations': locations
        }), 200
    except Exception as e:
        logger.exception("Error in get_locations")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@locations_bp.route('/<location_id>', methods=['GET'])
@token_required
def get_location(current_user, location_id):
    """Get a specific location by ID"""
    try:
        org_id, err = _resolve_org_scope()
        if err:
            return err
        location = FirebaseService.get_location(location_id, org_id)
        if not location:
            return jsonify({
                'success': False,
                'error': 'Location not found'
            }), 404

        return jsonify({
            'success': True,
            'location': location
        }), 200
    except Exception as e:
        logger.exception("Error in get_location")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@locations_bp.route('', methods=['POST'])
@token_required
@role_required('super_admin', 'location_admin')
def create_location(current_user):
    """Create a new location"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        # Validate required fields
        if not data.get('name'):
            return jsonify({'success': False, 'error': 'Missing required field: name'}), 400

        maps_link = data.get('google_maps_link', '')

        # A Google Maps link is the source of truth for the pin: its place
        # marker is used, never the map centre. A link with no place marker
        # (or one that can't be read) saves the venue without a pin from the
        # link and flags it for confirmation -- coordinates sent alongside a
        # link are ignored, since they would be a guess at the same thing.
        coords = None
        pin_needs_confirmation = False
        if maps_link:
            found = resolve_maps_link(maps_link)
            if found and found['kind'] in PIN_KINDS:
                coords = {'latitude': found['latitude'], 'longitude': found['longitude']}
            else:
                pin_needs_confirmation = True
        else:
            # No link: use explicitly provided lat/lng, if any
            has_lat = data.get('latitude') is not None
            has_lng = data.get('longitude') is not None
            if has_lat and has_lng:
                try:
                    lat = float(data['latitude'])
                    lng = float(data['longitude'])
                    if (-90 <= lat <= 90) and (-180 <= lng <= 180):
                        coords = {'latitude': lat, 'longitude': lng}
                except (ValueError, TypeError):
                    pass

        org_id, err = _resolve_org_scope()
        if err:
            return err
        # A new location always belongs to the caller's own organisation
        # (never to a body-supplied org_id). A caller with no org of their
        # own (cross-org super_admin) has nowhere to put it, and a location
        # with no org would be invisible to every org.
        if org_id is None:
            return jsonify({'success': False, 'error': 'Organisation context missing'}), 403

        # Create location
        location_data = {
            'name': data['name'],
            'address': data.get('address', ''),
            'google_maps_link': maps_link,
            'radius': data.get('radius', 100),
            'notes': data.get('notes', ''),
            'org_id': org_id,
            'pin_needs_confirmation': pin_needs_confirmation,
        }
        if coords:
            location_data['latitude'] = coords['latitude']
            location_data['longitude'] = coords['longitude']

        location = FirebaseService.create_location(location_data)

        return jsonify({
            'success': True,
            'location': location,
            'message': 'Location created successfully'
        }), 201
    except Exception as e:
        logger.exception("Error in create_location")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@locations_bp.route('/<location_id>', methods=['PUT'])
@token_required
@role_required('super_admin', 'location_admin')
def update_location(current_user, location_id):
    """Update a location"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        org_id, err = _resolve_org_scope()
        if err:
            return err

        # Check if location exists
        location = FirebaseService.get_location(location_id, org_id)
        if not location:
            return jsonify({
                'success': False,
                'error': 'Location not found'
            }), 404

        # If a maps link is provided, its place marker (never the map centre)
        # is the pin. Coordinates sent alongside a link are ignored.
        #   - real place point: pin updated, confirmation flag cleared
        #   - link has only a map centre: existing pin kept, flagged
        #   - link couldn't be read (e.g. Google unreachable): flagged, unless
        #     it is the same link the venue already had and that wasn't flagged
        pin_flag = None
        maps_link = data.get('google_maps_link')
        if maps_link:
            data.pop('latitude', None)
            data.pop('longitude', None)
            found = resolve_maps_link(maps_link)
            if found and found['kind'] in PIN_KINDS:
                data['latitude'] = found['latitude']
                data['longitude'] = found['longitude']
                pin_flag = False
            elif found is None and maps_link == location.get('google_maps_link') and not location.get('pin_needs_confirmation'):
                pin_flag = None  # transient failure on an unchanged, trusted link: leave as is
            else:
                pin_flag = True
        elif data.get('latitude') is not None and data.get('longitude') is not None:
            pin_flag = False  # a person supplied the coordinates directly

        # Update allowed fields
        update_data = {}
        allowed_fields = ['name', 'address', 'google_maps_link', 'radius', 'notes', 'latitude', 'longitude']
        for field in allowed_fields:
            if field in data:
                update_data[field] = data[field]

        if pin_flag is not None:
            update_data['pin_needs_confirmation'] = pin_flag

        if not update_data:
            return jsonify({
                'success': False,
                'error': 'No valid fields to update'
            }), 400

        # Update location
        updated_location = FirebaseService.update_location(location_id, update_data)

        return jsonify({
            'success': True,
            'location': updated_location,
            'message': 'Location updated successfully'
        }), 200
    except Exception as e:
        logger.exception("Error in update_location")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@locations_bp.route('/<location_id>', methods=['DELETE'])
@token_required
@role_required('super_admin', 'location_admin')
def delete_location(current_user, location_id):
    """Delete a location"""
    try:
        org_id, err = _resolve_org_scope()
        if err:
            return err

        # Check if location exists
        location = FirebaseService.get_location(location_id, org_id)
        if not location:
            return jsonify({
                'success': False,
                'error': 'Location not found'
            }), 404

        # Delete location
        FirebaseService.delete_location(location_id)

        return jsonify({
            'success': True,
            'message': 'Location deleted successfully'
        }), 200
    except Exception as e:
        logger.exception("Error in delete_location")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@locations_bp.route('/geocode', methods=['POST'])
@token_required
def geocode_location(current_user):
    """Geocode a free-text address to coordinates server-side, so the
    Google Maps API key never has to be exposed in the frontend bundle."""
    try:
        org_id, err = _resolve_org_scope()
        if err:
            return err

        data = request.get_json()
        if not data or not data.get('address'):
            return jsonify({'success': False, 'error': 'Missing required field: address'}), 400

        client_ip = get_trusted_client_ip(request.headers, remote_addr=request.remote_addr, allow_remote_addr_fallback=Config.DEBUG)
        user_rate_limited = is_rate_limited(f"geocode:user:{current_user}", *GEOCODE_USER_RATE_LIMIT)
        ip_rate_limited = is_rate_limited(f"geocode:ip:{client_ip}", *GEOCODE_IP_RATE_LIMIT)
        if user_rate_limited or ip_rate_limited:
            return jsonify({'success': False, 'error': 'Too many geocoding requests. Please try again later.'}), 429

        coords = geocode_address(data['address'])
        if not coords:
            return jsonify({'success': False, 'error': 'Address could not be geocoded'}), 404

        return jsonify({
            'success': True,
            'latitude': coords['latitude'],
            'longitude': coords['longitude'],
        }), 200
    except Exception as e:
        logger.exception("Error in geocode_location")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500
