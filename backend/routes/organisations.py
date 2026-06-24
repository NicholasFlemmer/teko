import logging
from flask import Blueprint, request, jsonify
from services.firebase_service import FirebaseService
from routes.auth import token_required

logger = logging.getLogger(__name__)

organisations_bp = Blueprint('organisations', __name__)


@organisations_bp.route('', methods=['GET'])
@token_required
def get_organisations(current_user):
    """Get all organisations. Super-admin only — for now a valid JWT suffices."""
    try:
        orgs = FirebaseService.get_all_organisations()
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
