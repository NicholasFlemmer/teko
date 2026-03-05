from flask import Blueprint, request, jsonify
from services.firebase_service import FirebaseService
from routes.auth import token_required

players_bp = Blueprint('players', __name__)

@players_bp.route('', methods=['GET'])
@token_required
def get_players(current_user):
    """Get all players with optional team_id filter"""
    try:
        team_id = request.args.get('team_id')
        players = FirebaseService.get_all_players(team_id=team_id)
        return jsonify({
            'success': True,
            'players': players
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@players_bp.route('/<player_id>', methods=['GET'])
@token_required
def get_player(current_user, player_id):
    """Get a specific player by ID"""
    try:
        player = FirebaseService.get_player(player_id)
        if not player:
            return jsonify({
                'success': False,
                'error': 'Player not found'
            }), 404

        return jsonify({
            'success': True,
            'player': player
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@players_bp.route('', methods=['POST'])
@token_required
def create_player(current_user):
    """Create a new player"""
    try:
        data = request.get_json()

        # Validate required fields
        required_fields = ['first_name', 'last_name']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }), 400

        # Create player
        player = FirebaseService.create_player({
            'first_name': data['first_name'],
            'last_name': data['last_name'],
            'date_of_birth': data.get('date_of_birth', ''),
            'guardian_name': data.get('guardian_name', ''),
            'guardian_email': data.get('guardian_email', ''),
            'guardian_primary_phone': data.get('guardian_primary_phone', ''),
            'guardian_secondary_phone': data.get('guardian_secondary_phone', ''),
            'special_notes': data.get('special_notes', ''),
            'team_ids': data.get('team_ids', [])
        })

        return jsonify({
            'success': True,
            'player': player,
            'message': 'Player created successfully'
        }), 201
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@players_bp.route('/<player_id>', methods=['PUT'])
@token_required
def update_player(current_user, player_id):
    """Update a player"""
    try:
        data = request.get_json()

        # Check if player exists
        player = FirebaseService.get_player(player_id)
        if not player:
            return jsonify({
                'success': False,
                'error': 'Player not found'
            }), 404

        # Update allowed fields
        update_data = {}
        allowed_fields = ['first_name', 'last_name', 'date_of_birth', 'guardian_name',
                          'guardian_email', 'guardian_primary_phone',
                          'guardian_secondary_phone', 'special_notes', 'team_ids']
        for field in allowed_fields:
            if field in data:
                update_data[field] = data[field]

        if not update_data:
            return jsonify({
                'success': False,
                'error': 'No valid fields to update'
            }), 400

        # Update player
        updated_player = FirebaseService.update_player(player_id, update_data)

        return jsonify({
            'success': True,
            'player': updated_player,
            'message': 'Player updated successfully'
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@players_bp.route('/<player_id>', methods=['DELETE'])
@token_required
def delete_player(current_user, player_id):
    """Delete a player"""
    try:
        # Check if player exists
        player = FirebaseService.get_player(player_id)
        if not player:
            return jsonify({
                'success': False,
                'error': 'Player not found'
            }), 404

        # Delete player
        FirebaseService.delete_player(player_id)

        return jsonify({
            'success': True,
            'message': 'Player deleted successfully'
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
