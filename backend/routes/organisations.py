import logging
from flask import Blueprint, request, jsonify, g
from services.firebase_service import FirebaseService
from routes.auth import token_required

logger = logging.getLogger(__name__)

organisations_bp = Blueprint('organisations', __name__)


@organisations_bp.route('', methods=['GET'])
@token_required
def get_organisations(current_user):
    """List organisations, scoped by the caller's role.

    Super admins see every org; everyone else sees only their own org.
    """
    try:
        role = getattr(g, 'current_user_role', None)
        if role == 'super_admin':
            orgs = FirebaseService.get_all_organisations()
        else:
            org_id = getattr(g, 'current_user_org_id', None)
            org = FirebaseService.get_organisation(org_id) if org_id else None
            orgs = [org] if org else []
        return jsonify({
            'success': True,
            'organisations': orgs
        }), 200
    except Exception as e:
        logger.exception("Error in get_organisations")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500


@organisations_bp.route('/<org_id>', methods=['GET'])
@token_required
def get_organisation(current_user, org_id):
    """Get a single organisation by ID."""
    try:
        org = FirebaseService.get_organisation(org_id)
        if not org:
            return jsonify({
                'success': False,
                'error': 'Organisation not found'
            }), 404
        return jsonify({
            'success': True,
            'organisation': org
        }), 200
    except Exception as e:
        logger.exception("Error in get_organisation")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500


@organisations_bp.route('/<org_id>', methods=['PUT'])
@token_required
def update_organisation(current_user, org_id):
    """Update an organisation's name, type and/or terminology."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        org = FirebaseService.get_organisation(org_id)
        if not org:
            return jsonify({
                'success': False,
                'error': 'Organisation not found'
            }), 404

        update_data = {}
        allowed_fields = ['name', 'type', 'terminology']
        for field in allowed_fields:
            if field in data:
                update_data[field] = data[field]

        if not update_data:
            return jsonify({
                'success': False,
                'error': 'No valid fields to update'
            }), 400

        updated = FirebaseService.update_organisation(org_id, update_data)
        return jsonify({
            'success': True,
            'organisation': updated
        }), 200
    except Exception as e:
        logger.exception("Error in update_organisation")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500


@organisations_bp.route('/<org_id>/terminology', methods=['GET'])
@token_required
def get_organisation_terminology(current_user, org_id):
    """Get just the terminology object for an organisation (with defaults)."""
    try:
        terminology = FirebaseService.get_org_terminology(org_id)
        return jsonify({
            'success': True,
            'terminology': terminology
        }), 200
    except Exception as e:
        logger.exception("Error in get_organisation_terminology")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500


# Mounted at /api/admins (registered separately in app.py) so the path is
# /api/admins rather than under the /api/organisations prefix.
admins_bp = Blueprint('admins', __name__)


@admins_bp.route('', methods=['GET'])
@token_required
def get_admins(current_user):
    """List admins for the caller's org.

    Super and location admins see every admin in their org (location-level
    filtering for location admins comes later). Any other role sees only their
    own record, matched by admin document id from the JWT.
    """
    try:
        org_id = getattr(g, 'current_user_org_id', None)
        role = getattr(g, 'current_user_role', None)
        admins = FirebaseService.get_all_admins_by_org(org_id)

        if role not in ('super_admin', 'location_admin'):
            current_user_id = getattr(g, 'current_user_id', None)
            admins = [a for a in admins if a.get('id') == current_user_id]

        return jsonify({
            'success': True,
            'admins': admins
        }), 200
    except Exception as e:
        logger.exception("Error in get_admins")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500
