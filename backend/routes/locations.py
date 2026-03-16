import logging
from flask import Blueprint, request, jsonify
from services.firebase_service import FirebaseService
from routes.auth import token_required
from utils.geolocation import extract_coords_from_maps_url

logger = logging.getLogger(__name__)

locations_bp = Blueprint('locations', __name__)

@locations_bp.route('', methods=['GET'])
@token_required
def get_locations(current_user):
    """Get all locations"""
    try:
        locations = FirebaseService.get_all_locations()
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
        location = FirebaseService.get_location(location_id)
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

        # Google Maps link is the source of truth for coordinates
        coords = extract_coords_from_maps_url(maps_link) if maps_link else None

        # Fall back to explicitly provided lat/lng if no maps link
        if not coords:
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

        # Create location
        location_data = {
            'name': data['name'],
            'address': data.get('address', ''),
            'google_maps_link': maps_link,
            'radius': data.get('radius', 100),
            'notes': data.get('notes', '')
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
def update_location(current_user, location_id):
    """Update a location"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        # Check if location exists
        location = FirebaseService.get_location(location_id)
        if not location:
            return jsonify({
                'success': False,
                'error': 'Location not found'
            }), 404

        # If maps link is provided/changed, re-derive coordinates from it
        maps_link = data.get('google_maps_link')
        if maps_link:
            coords = extract_coords_from_maps_url(maps_link)
            if coords:
                data['latitude'] = coords['latitude']
                data['longitude'] = coords['longitude']

        # Update allowed fields
        update_data = {}
        allowed_fields = ['name', 'address', 'google_maps_link', 'radius', 'notes', 'latitude', 'longitude']
        for field in allowed_fields:
            if field in data:
                update_data[field] = data[field]

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
def delete_location(current_user, location_id):
    """Delete a location"""
    try:
        # Check if location exists
        location = FirebaseService.get_location(location_id)
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
