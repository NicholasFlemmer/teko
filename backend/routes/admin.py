from flask import Blueprint, request, jsonify
from services.firebase_service import FirebaseService
from routes.auth import token_required

admin_bp = Blueprint('admin', __name__)

# --- Admin Users ---

@admin_bp.route('/users', methods=['GET'])
@token_required
def get_admin_users(current_user):
    """Get all admin users"""
    try:
        users = FirebaseService.get_all_admins()
        return jsonify({
            'success': True,
            'admins': users
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/users', methods=['POST'])
@token_required
def create_admin_user(current_user):
    """Create a new admin user"""
    try:
        data = request.get_json()

        # Validate required fields
        required_fields = ['name', 'email', 'password', 'role']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }), 400

        # Create admin user
        user = FirebaseService.create_admin({
            'name': data['name'],
            'email': data['email'],
            'password': data['password'],
            'role': data['role']
        })

        return jsonify({
            'success': True,
            'admin': user,
            'message': 'Admin user created successfully'
        }), 201
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/users/<admin_id>', methods=['PUT'])
@token_required
def update_admin_user(current_user, admin_id):
    """Update an admin user"""
    try:
        data = request.get_json()

        # Check if admin user exists
        user = FirebaseService.get_admin(admin_id)
        if not user:
            return jsonify({
                'success': False,
                'error': 'Admin user not found'
            }), 404

        # Update allowed fields
        update_data = {}
        allowed_fields = ['name', 'email', 'password', 'role']
        for field in allowed_fields:
            if field in data:
                update_data[field] = data[field]

        if not update_data:
            return jsonify({
                'success': False,
                'error': 'No valid fields to update'
            }), 400

        # Update admin user
        updated_user = FirebaseService.update_admin(admin_id, update_data)

        return jsonify({
            'success': True,
            'admin': updated_user,
            'message': 'Admin user updated successfully'
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/users/<admin_id>', methods=['DELETE'])
@token_required
def delete_admin_user(current_user, admin_id):
    """Delete an admin user"""
    try:
        # Check if admin user exists
        user = FirebaseService.get_admin(admin_id)
        if not user:
            return jsonify({
                'success': False,
                'error': 'Admin user not found'
            }), 404

        # Delete admin user
        FirebaseService.delete_admin(admin_id)

        return jsonify({
            'success': True,
            'message': 'Admin user deleted successfully'
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/users/<admin_id>/toggle-status', methods=['PUT'])
@token_required
def toggle_admin_status(current_user, admin_id):
    """Toggle an admin user's active/suspended status"""
    try:
        # Check if admin user exists
        user = FirebaseService.get_admin(admin_id)
        if not user:
            return jsonify({
                'success': False,
                'error': 'Admin user not found'
            }), 404

        # Toggle status
        current_status = user.get('status', 'active')
        new_status = 'suspended' if current_status == 'active' else 'active'

        updated_user = FirebaseService.update_admin(admin_id, {'status': new_status})

        return jsonify({
            'success': True,
            'admin': updated_user,
            'message': f'Admin user status changed to {new_status}'
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# --- System Settings ---

@admin_bp.route('/settings', methods=['GET'])
@token_required
def get_settings(current_user):
    """Get system settings"""
    try:
        settings = FirebaseService.get_settings()
        return jsonify({
            'success': True,
            'settings': settings
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/settings', methods=['PUT'])
@token_required
def update_settings(current_user):
    """Save system settings"""
    try:
        data = request.get_json()

        # Update allowed fields
        update_data = {}
        allowed_fields = ['maintenance_mode', 'auto_backup', 'sender_email', 'sender_name']
        for field in allowed_fields:
            if field in data:
                update_data[field] = data[field]

        if not update_data:
            return jsonify({
                'success': False,
                'error': 'No valid fields to update'
            }), 400

        # Save settings
        settings = FirebaseService.update_settings(update_data)

        return jsonify({
            'success': True,
            'settings': settings,
            'message': 'Settings updated successfully'
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
