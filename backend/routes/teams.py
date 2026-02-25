from flask import Blueprint, request, jsonify
from services.firebase_service import FirebaseService
from routes.auth import token_required

teams_bp = Blueprint('teams', __name__)

@teams_bp.route('', methods=['GET'])
@token_required
def get_teams(current_user):
    """Get all teams with optional location filter"""
    try:
        location_id = request.args.get('location_id')
        teams = FirebaseService.get_all_teams(location_id=location_id)
        return jsonify({
            'success': True,
            'teams': teams
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@teams_bp.route('/<team_id>', methods=['GET'])
@token_required
def get_team(current_user, team_id):
    """Get a specific team by ID"""
    try:
        team = FirebaseService.get_team(team_id)
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
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@teams_bp.route('', methods=['POST'])
@token_required
def create_team(current_user):
    """Create a new team"""
    try:
        data = request.get_json()

        # Validate required fields
        required_fields = ['name', 'age_group', 'location_id', 'coach_ids']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }), 400

        # Create team
        team = FirebaseService.create_team({
            'name': data['name'],
            'age_group': data['age_group'],
            'location_id': data['location_id'],
            'coach_ids': data['coach_ids']
        })

        return jsonify({
            'success': True,
            'team': team,
            'message': 'Team created successfully'
        }), 201
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@teams_bp.route('/<team_id>', methods=['PUT'])
@token_required
def update_team(current_user, team_id):
    """Update a team"""
    try:
        data = request.get_json()

        # Check if team exists
        team = FirebaseService.get_team(team_id)
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
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@teams_bp.route('/<team_id>', methods=['DELETE'])
@token_required
def delete_team(current_user, team_id):
    """Delete a team"""
    try:
        # Check if team exists
        team = FirebaseService.get_team(team_id)
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
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
