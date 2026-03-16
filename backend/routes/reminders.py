import logging
from flask import Blueprint, request, jsonify
from services.firebase_service import FirebaseService
from routes.auth import token_required

logger = logging.getLogger(__name__)

reminders_bp = Blueprint('reminders', __name__)

@reminders_bp.route('', methods=['GET'])
@token_required
def get_reminders(current_user):
    """Get all reminder configurations"""
    try:
        reminders = FirebaseService.get_all_reminders()
        return jsonify({
            'success': True,
            'reminders': reminders
        }), 200
    except Exception as e:
        logger.exception("Error in get_reminders")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@reminders_bp.route('', methods=['POST'])
@token_required
def create_reminder(current_user):
    """Create a new reminder configuration"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        # Validate required fields
        required_fields = ['type', 'timing', 'enabled']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }), 400

        # Create reminder config
        reminder = FirebaseService.create_reminder({
            'type': data['type'],
            'timing': data['timing'],
            'enabled': data['enabled'],
            'description': data.get('description', '')
        })

        return jsonify({
            'success': True,
            'reminder': reminder,
            'message': 'Reminder created successfully'
        }), 201
    except Exception as e:
        logger.exception("Error in create_reminder")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@reminders_bp.route('/<reminder_id>', methods=['PUT'])
@token_required
def update_reminder(current_user, reminder_id):
    """Update a reminder configuration"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        # Check if reminder exists
        reminder = FirebaseService.get_reminder(reminder_id)
        if not reminder:
            return jsonify({
                'success': False,
                'error': 'Reminder not found'
            }), 404

        # Update allowed fields
        update_data = {}
        allowed_fields = ['type', 'timing', 'enabled', 'description']
        for field in allowed_fields:
            if field in data:
                update_data[field] = data[field]

        if not update_data:
            return jsonify({
                'success': False,
                'error': 'No valid fields to update'
            }), 400

        # Update reminder
        updated_reminder = FirebaseService.update_reminder(reminder_id, update_data)

        return jsonify({
            'success': True,
            'reminder': updated_reminder,
            'message': 'Reminder updated successfully'
        }), 200
    except Exception as e:
        logger.exception("Error in update_reminder")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@reminders_bp.route('/<reminder_id>', methods=['DELETE'])
@token_required
def delete_reminder(current_user, reminder_id):
    """Delete a reminder configuration"""
    try:
        # Check if reminder exists
        reminder = FirebaseService.get_reminder(reminder_id)
        if not reminder:
            return jsonify({
                'success': False,
                'error': 'Reminder not found'
            }), 404

        # Delete reminder
        FirebaseService.delete_reminder(reminder_id)

        return jsonify({
            'success': True,
            'message': 'Reminder deleted successfully'
        }), 200
    except Exception as e:
        logger.exception("Error in delete_reminder")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500
