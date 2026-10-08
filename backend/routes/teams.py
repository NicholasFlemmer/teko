import logging
from flask import Blueprint, request, jsonify, g
from services.firebase_service import FirebaseService
from routes.auth import token_required

logger = logging.getLogger(__name__)

# Roles allowed to set which coaches belong to a team.
COACH_ASSIGN_ROLES = ('super_admin', 'location_admin')

teams_bp = Blueprint('teams', __name__)


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


def _validate_coach_ids(raw, team_org_id):
    """Validate a coach_ids payload for a team in team_org_id.

    Returns (clean_list, None) on success, or (None, error_response). Every
    id must be a string naming an existing coach in the same org as the
    team; an unknown id and an id from another org are rejected the same
    way (get_coach returns None for both), so the response never reveals
    whether a coach exists in another org. Only the admin roles may write
    coach_ids.
    """
    if getattr(g, 'current_user_role', None) not in COACH_ASSIGN_ROLES:
        return None, (jsonify({'success': False, 'error': 'Insufficient permissions'}), 403)
    if not isinstance(raw, list) or not all(isinstance(c, str) and c.strip() for c in raw):
        return None, (jsonify({'success': False, 'error': 'coach_ids must be a list of coach ids'}), 400)
    clean = list(dict.fromkeys(c.strip() for c in raw))
    if not clean:
        return clean, None
    if team_org_id is None:
        return None, (jsonify({'success': False, 'error': 'Organisation context missing'}), 403)
    for coach_id in clean:
        if not FirebaseService.get_coach(coach_id, team_org_id):
            return None, (jsonify({
                'success': False,
                'error': 'One or more coaches do not exist in this organisation',
            }), 400)
    return clean, None


@teams_bp.route('', methods=['GET'])
@token_required
def get_teams(current_user):
    """Get all teams with optional location filter"""
    try:
        org_id, err = _resolve_org_scope()
        if err:
            return err
        location_id = request.args.get('location_id')
        teams = FirebaseService.get_all_teams(org_id, location_id=location_id)
        return jsonify({
            'success': True,
            'teams': teams
        }), 200
    except Exception as e:
        logger.exception("Error in get_teams")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@teams_bp.route('/<team_id>', methods=['GET'])
@token_required
def get_team(current_user, team_id):
    """Get a specific team by ID"""
    try:
        org_id, err = _resolve_org_scope()
        if err:
            return err
        team = FirebaseService.get_team(team_id, org_id)
        if not team:
            return jsonify({
                'success': False,
                'error': 'Team not found'
            }), 404

        return jsonify({
            'success': True,
            'team': team
        }), 200
    except Exception as e:
        logger.exception("Error in get_team")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@teams_bp.route('', methods=['POST'])
@token_required
def create_team(current_user):
    """Create a new team"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        # Validate required fields
        required_fields = ['name', 'age_group']
        for field in required_fields:
            if field not in data or not str(data[field]).strip():
                return jsonify({
                    'success': False,
                    'error': f'Missing or empty required field: {field}'
                }), 400

        org_id, err = _resolve_org_scope()
        if err:
            return err

        coach_ids = []
        if 'coach_ids' in data:
            coach_ids, err = _validate_coach_ids(data['coach_ids'], org_id)
            if err:
                return err

        # Create team
        team = FirebaseService.create_team({
            'name': data['name'],
            'age_group': data['age_group'],
            'location_id': data.get('location_id', ''),
            'coach_ids': coach_ids,
            'org_id': org_id,
        })

        return jsonify({
            'success': True,
            'team': team,
            'message': 'Team created successfully'
        }), 201
    except Exception as e:
        logger.exception("Error in create_team")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@teams_bp.route('/<team_id>', methods=['PUT'])
@token_required
def update_team(current_user, team_id):
    """Update a team"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        org_id, err = _resolve_org_scope()
        if err:
            return err

        # Check if team exists
        team = FirebaseService.get_team(team_id, org_id)
        if not team:
            return jsonify({
                'success': False,
                'error': 'Team not found'
            }), 404

        # Update allowed fields
        update_data = {}
        allowed_fields = ['name', 'age_group', 'location_id', 'coach_ids']
        for field in allowed_fields:
            if field in data:
                update_data[field] = data[field]

        if 'coach_ids' in update_data:
            # Validate against the team's own org, not the caller's, so a
            # super_admin (org_id None) is held to the same rule.
            clean, err = _validate_coach_ids(update_data['coach_ids'], team.get('org_id'))
            if err:
                return err
            update_data['coach_ids'] = clean

        if not update_data:
            return jsonify({
                'success': False,
                'error': 'No valid fields to update'
            }), 400

        # Update team
        updated_team = FirebaseService.update_team(team_id, update_data)

        return jsonify({
            'success': True,
            'team': updated_team,
            'message': 'Team updated successfully'
        }), 200
    except Exception as e:
        logger.exception("Error in update_team")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@teams_bp.route('/<team_id>', methods=['DELETE'])
@token_required
def delete_team(current_user, team_id):
    """Delete a team"""
    try:
        org_id, err = _resolve_org_scope()
        if err:
            return err

        # Check if team exists
        team = FirebaseService.get_team(team_id, org_id)
        if not team:
            return jsonify({
                'success': False,
                'error': 'Team not found'
            }), 404

        # Delete team
        FirebaseService.delete_team(team_id)

        return jsonify({
            'success': True,
            'message': 'Team deleted successfully'
        }), 200
    except Exception as e:
        logger.exception("Error in delete_team")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500
