import logging
from flask import Blueprint, request, jsonify, g
from services.firebase_service import FirebaseService
from routes.auth import token_required
from utils.phone import normalize_phone_for_matching

logger = logging.getLogger(__name__)

participants_bp = Blueprint('participants', __name__)


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


@participants_bp.route('', methods=['GET'])
@token_required
def get_participants(current_user):
    """Get all participants"""
    try:
        org_id, err = _resolve_org_scope()
        if err:
            return err
        participants = FirebaseService.get_all_participants(org_id)
        return jsonify({
            'success': True,
            'participants': participants
        }), 200
    except Exception as e:
        logger.exception("Error in get_participants")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@participants_bp.route('/<participant_id>', methods=['GET'])
@token_required
def get_participant(current_user, participant_id):
    """Get a specific participant by ID"""
    try:
        org_id, err = _resolve_org_scope()
        if err:
            return err
        participant = FirebaseService.get_participant(org_id, participant_id)
        if not participant:
            return jsonify({
                'success': False,
                'error': 'Participant not found'
            }), 404

        return jsonify({
            'success': True,
            'participant': participant
        }), 200
    except Exception as e:
        logger.exception("Error in get_participant")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@participants_bp.route('', methods=['POST'])
@token_required
def create_participant(current_user):
    """Create a new participant"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        if 'name' not in data:
            return jsonify({
                'success': False,
                'error': 'Missing required field: name'
            }), 400

        name_val = (data.get('name') or '').strip()
        if not name_val:
            return jsonify({'success': False, 'error': 'Name cannot be empty'}), 400

        org_id, err = _resolve_org_scope()
        if err:
            return err

        # Build participant data
        participant_data = {
            'name': data['name'],
        }

        # Phone number - normalize on save. SA numbers get their canonical
        # 27XXXXXXXXX form; non-SA numbers (e.g. a Brazilian participant)
        # get the permissive strip-only form rather than being rejected or
        # blanked — normalize_sa_phone() alone would reject them outright.
        raw_phone = data.get('phone_number') or data.get('phone', '')
        if raw_phone:
            participant_data['phone_number'] = normalize_phone_for_matching(raw_phone) or raw_phone

        if 'active' in data:
            participant_data['active'] = bool(data['active'])

        # Create participant
        participant = FirebaseService.create_participant(org_id, participant_data)

        return jsonify({
            'success': True,
            'participant': participant,
            'message': 'Participant created successfully'
        }), 201
    except Exception as e:
        logger.exception("Error in create_participant")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@participants_bp.route('/<participant_id>', methods=['PUT'])
@token_required
def update_participant(current_user, participant_id):
    """Update a participant"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        org_id, err = _resolve_org_scope()
        if err:
            return err

        # Update allowed fields
        update_data = {}
        allowed_fields = ['name', 'phone_number', 'phone', 'active']
        for field in allowed_fields:
            if field in data:
                # Normalize phone fields on save
                if field in ('phone', 'phone_number'):
                    normalized = normalize_phone_for_matching(data[field])
                    update_data['phone_number'] = normalized or data[field]
                else:
                    update_data[field] = data[field]

        if not update_data:
            return jsonify({
                'success': False,
                'error': 'No valid fields to update'
            }), 400

        # Update participant (also verifies ownership; None means not found/wrong org)
        updated_participant = FirebaseService.update_participant(org_id, participant_id, update_data)
        if not updated_participant:
            return jsonify({
                'success': False,
                'error': 'Participant not found'
            }), 404

        return jsonify({
            'success': True,
            'participant': updated_participant,
            'message': 'Participant updated successfully'
        }), 200
    except Exception as e:
        logger.exception("Error in update_participant")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@participants_bp.route('/<participant_id>', methods=['DELETE'])
@token_required
def delete_participant(current_user, participant_id):
    """Delete a participant"""
    try:
        org_id, err = _resolve_org_scope()
        if err:
            return err

        # Delete participant (also verifies ownership; False means not found/wrong org)
        deleted = FirebaseService.delete_participant(org_id, participant_id)
        if not deleted:
            return jsonify({
                'success': False,
                'error': 'Participant not found'
            }), 404

        return jsonify({
            'success': True,
            'message': 'Participant deleted successfully'
        }), 200
    except Exception as e:
        logger.exception("Error in delete_participant")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500
