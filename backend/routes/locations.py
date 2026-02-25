from flask import Blueprint, request, jsonify
from services.firebase_service import FirebaseService
from routes.auth import token_required

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
        return jsonify({
            'success': False,
            'error': str(e)
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
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@locations_bp.route('', methods=['POST'])
@token_required
def create_location(current_user):
    """Create a new location"""
    try:
        data = request.get_json()

        # Validate required fields
        required_fields = ['name', 'address']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }), 400

        # Create location
        location = FirebaseService.create_location({
            'name': data['name'],
            'address': data['address'],
            'google_maps_link': data.get('google_maps_link', ''),
            'radius': data.get('radius', 100),
            'notes': data.get('notes', '')
        })

        return jsonify({
            'success': True,
            'location': location,
            'message': 'Location created successfully'
        }), 201
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@locations_bp.route('/<location_id>', methods=['PUT'])
@token_required
def update_location(current_user, location_id):
    """Update a location"""
    try:
        data = request.get_json()

        # Check if location exists
        location = FirebaseService.get_location(location_id)
        if not location:
            return jsonify({
                'success': False,
                'error': 'Location not found'
            }), 404

        # Update allowed fields
        update_data = {}
        allowed_fields = ['name', 'address', 'google_maps_link', 'radius', 'notes']
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
        return jsonify({
            'success': False,
            'error': str(e)
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
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
