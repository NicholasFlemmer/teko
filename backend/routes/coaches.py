import logging
from flask import Blueprint, request, jsonify
from services.firebase_service import FirebaseService
from routes.auth import token_required

logger = logging.getLogger(__name__)

coaches_bp = Blueprint('coaches', __name__)

@coaches_bp.route('', methods=['GET'])
@token_required
def get_coaches(current_user):
    """Get all coaches"""
    try:
        coaches = FirebaseService.get_all_coaches()
        return jsonify({
            'success': True,
            'coaches': coaches
        }), 200
    except Exception as e:
        logger.exception("Error in get_coaches")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@coaches_bp.route('/<coach_id>', methods=['GET'])
@token_required
def get_coach(current_user, coach_id):
    """Get a specific coach by ID"""
    try:
        coach = FirebaseService.get_coach(coach_id)
        if not coach:
            return jsonify({
                'success': False,
                'error': 'Coach not found'
            }), 404

        return jsonify({
            'success': True,
            'coach': coach
        }), 200
    except Exception as e:
        logger.exception("Error in get_coach")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@coaches_bp.route('', methods=['POST'])
@token_required
def create_coach(current_user):
    """Create a new coach"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        # Validate required fields - support both old (name) and new (first_name/last_name) formats
        if 'name' not in data and 'first_name' not in data:
            return jsonify({
                'success': False,
                'error': 'Missing required field: name or first_name'
            }), 400

        if 'email' not in data:
            return jsonify({
                'success': False,
                'error': 'Missing required field: email'
            }), 400

        # Validate non-empty values
        name_val = (data.get('first_name') or data.get('name') or '').strip()
        email_val = (data.get('email') or '').strip()
        if not name_val:
            return jsonify({'success': False, 'error': 'Name cannot be empty'}), 400
        if not email_val:
            return jsonify({'success': False, 'error': 'Email cannot be empty'}), 400

        # Build coach data
        coach_data = {
            'email': data['email'],
        }

        # Support both old format (name) and new format (first_name/last_name)
        if 'first_name' in data:
            coach_data['first_name'] = data['first_name']
            coach_data['last_name'] = data.get('last_name', '')
            coach_data['name'] = f"{data['first_name']} {data.get('last_name', '')}".strip()
        elif 'name' in data:
            coach_data['name'] = data['name']
            parts = data['name'].split(' ', 1)
            coach_data['first_name'] = parts[0]
            coach_data['last_name'] = parts[1] if len(parts) > 1 else ''

        # Phone number - support both formats
        coach_data['phone_number'] = data.get('phone_number') or data.get('phone', '')

        # Optional expanded fields
        optional_fields = ['dob', 'profile_picture', 'emergency_name', 'emergency_relationship',
                          'emergency_phone', 'notes', 'joined_date']
        for field in optional_fields:
            if field in data:
                coach_data[field] = data[field]

        # Create coach
        coach = FirebaseService.create_coach(coach_data)

        return jsonify({
            'success': True,
            'coach': coach,
            'message': 'Coach created successfully'
        }), 201
    except Exception as e:
        logger.exception("Error in create_coach")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@coaches_bp.route('/<coach_id>', methods=['PUT'])
@token_required
def update_coach(current_user, coach_id):
    """Update a coach"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        # Check if coach exists
        coach = FirebaseService.get_coach(coach_id)
        if not coach:
            return jsonify({
                'success': False,
                'error': 'Coach not found'
            }), 404

        # Update allowed fields
        update_data = {}
        allowed_fields = ['name', 'first_name', 'last_name', 'phone_number', 'phone', 'email',
                          'dob', 'profile_picture', 'emergency_name', 'emergency_relationship',
                          'emergency_phone', 'notes', 'joined_date']
        for field in allowed_fields:
            if field in data:
                # Normalize phone field
                if field == 'phone':
                    update_data['phone_number'] = data[field]
                else:
                    update_data[field] = data[field]

        # Keep name in sync with first_name/last_name
        if 'first_name' in update_data or 'last_name' in update_data:
            fn = update_data.get('first_name', coach.get('first_name', ''))
            ln = update_data.get('last_name', coach.get('last_name', ''))
            update_data['name'] = f"{fn} {ln}".strip()

        if not update_data:
            return jsonify({
                'success': False,
                'error': 'No valid fields to update'
            }), 400

        # Update coach
        updated_coach = FirebaseService.update_coach(coach_id, update_data)

        return jsonify({
            'success': True,
            'coach': updated_coach,
            'message': 'Coach updated successfully'
        }), 200
    except Exception as e:
        logger.exception("Error in update_coach")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@coaches_bp.route('/<coach_id>', methods=['DELETE'])
@token_required
def delete_coach(current_user, coach_id):
    """Delete a coach"""
    try:
        # Check if coach exists
        coach = FirebaseService.get_coach(coach_id)
        if not coach:
            return jsonify({
                'success': False,
                'error': 'Coach not found'
            }), 404

        # Delete coach
        FirebaseService.delete_coach(coach_id)

        return jsonify({
            'success': True,
            'message': 'Coach deleted successfully'
        }), 200
    except Exception as e:
        logger.exception("Error in delete_coach")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500
