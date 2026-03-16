import logging
from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash
from services.firebase_service import FirebaseService
from routes.auth import token_required, role_required

logger = logging.getLogger(__name__)

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
        logger.exception("Error in get_admin_users")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@admin_bp.route('/users', methods=['POST'])
@token_required
@role_required('superadmin')
def create_admin_user(current_user):
    """Create a new admin user"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        # Validate required fields (must be present and non-empty)
        required_fields = ['name', 'email', 'password', 'role']
        for field in required_fields:
            if field not in data or not str(data[field]).strip():
                return jsonify({
                    'success': False,
                    'error': f'Missing or empty required field: {field}'
                }), 400

        # Validate role against allowed values
        allowed_roles = ['admin', 'superadmin', 'viewer']
        if data['role'] not in allowed_roles:
            return jsonify({'success': False, 'error': f'Role must be one of: {", ".join(allowed_roles)}'}), 400

        # Validate password length
        if len(data['password']) < 8:
            return jsonify({'success': False, 'error': 'Password must be at least 8 characters'}), 400

        # Check email uniqueness
        email = data['email'].strip().lower()
        existing = FirebaseService.get_admin_by_email(email)
        if existing:
            return jsonify({'success': False, 'error': 'An admin with this email already exists'}), 409

        # Create admin user with hashed password
        user = FirebaseService.create_admin({
            'name': data['name'].strip(),
            'email': email,
            'password': generate_password_hash(data['password']),
            'role': data['role']
        })

        return jsonify({
            'success': True,
            'admin': user,
            'message': 'Admin user created successfully'
        }), 201
    except Exception as e:
        logger.exception("Error in create_admin_user")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@admin_bp.route('/users/<admin_id>', methods=['PUT'])
@token_required
@role_required('superadmin')
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
                if field == 'password':
                    if len(data[field]) < 8:
                        return jsonify({'success': False, 'error': 'Password must be at least 8 characters'}), 400
                    update_data[field] = generate_password_hash(data[field])
                elif field == 'email':
                    email = data[field].strip().lower()
                    existing = FirebaseService.get_admin_by_email(email)
                    if existing and existing.get('id') != admin_id:
                        return jsonify({'success': False, 'error': 'An admin with this email already exists'}), 409
                    update_data[field] = email
                else:
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
        logger.exception("Error in update_admin_user")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@admin_bp.route('/users/<admin_id>', methods=['DELETE'])
@token_required
@role_required('superadmin')
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
        logger.exception("Error in delete_admin_user")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@admin_bp.route('/users/<admin_id>/toggle-status', methods=['PUT'])
@token_required
@role_required('superadmin')
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
        logger.exception("Error in toggle_admin_status")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
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
        logger.exception("Error in get_settings")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@admin_bp.route('/settings', methods=['PUT'])
@token_required
@role_required('superadmin', 'admin')
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
        logger.exception("Error in update_settings")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500
