import csv
import io
import logging
from flask import Blueprint, request, jsonify
from services.firebase_service import FirebaseService
from routes.auth import token_required

logger = logging.getLogger(__name__)

# Column name mappings: CSV header -> player field
_COLUMN_MAP = {
    'first_name': 'first_name', 'first name': 'first_name', 'firstname': 'first_name', 'name': 'first_name',
    'last_name': 'last_name', 'last name': 'last_name', 'lastname': 'last_name', 'surname': 'last_name',
    'date_of_birth': 'date_of_birth', 'date of birth': 'date_of_birth', 'dob': 'date_of_birth', 'birthday': 'date_of_birth', 'birth date': 'date_of_birth',
    'guardian_name': 'guardian_name', 'guardian name': 'guardian_name', 'parent': 'guardian_name', 'parent name': 'guardian_name',
    'guardian_email': 'guardian_email', 'guardian email': 'guardian_email', 'parent email': 'guardian_email',
    'guardian_primary_phone': 'guardian_primary_phone', 'guardian phone': 'guardian_primary_phone', 'parent phone': 'guardian_primary_phone', 'phone': 'guardian_primary_phone',
    'guardian_secondary_phone': 'guardian_secondary_phone', 'secondary phone': 'guardian_secondary_phone',
    'special_notes': 'special_notes', 'special notes': 'special_notes', 'notes': 'special_notes', 'medical': 'special_notes',
}

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
        logger.exception("Error in get_players")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
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
        logger.exception("Error in get_player")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@players_bp.route('', methods=['POST'])
@token_required
def create_player(current_user):
    """Create a new player"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        # Validate required fields
        required_fields = ['first_name', 'last_name']
        for field in required_fields:
            if field not in data or not str(data[field]).strip():
                return jsonify({
                    'success': False,
                    'error': f'Missing or empty required field: {field}'
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
        logger.exception("Error in create_player")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@players_bp.route('/<player_id>', methods=['PUT'])
@token_required
def update_player(current_user, player_id):
    """Update a player"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

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
        logger.exception("Error in update_player")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
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
        logger.exception("Error in delete_player")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500


def _map_columns(header_row):
    """Map CSV header names to player field names. Returns {col_index: field_name}."""
    mapping = {}
    for i, col in enumerate(header_row):
        normalised = col.strip().lower()
        if normalised in _COLUMN_MAP:
            mapping[i] = _COLUMN_MAP[normalised]
    return mapping


@players_bp.route('/bulk-upload', methods=['POST'])
@token_required
def bulk_upload_players(current_user):
    """Upload players from a CSV file.

    Expects multipart/form-data with:
      - file: CSV file
      - team_ids (optional, repeated): team IDs to assign all players to
    """
    try:
        file = request.files.get('file')
        if not file or not file.filename:
            return jsonify({'success': False, 'error': 'No file provided'}), 400

        filename = file.filename.lower()
        if not filename.endswith('.csv'):
            return jsonify({'success': False, 'error': 'Only CSV files are supported'}), 400

        team_ids = request.form.getlist('team_ids')

        # Read and decode the CSV
        try:
            raw = file.read()
            # Try UTF-8 first, fall back to latin-1
            try:
                text = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                text = raw.decode('latin-1')
        except Exception:
            return jsonify({'success': False, 'error': 'Could not read the file'}), 400

        reader = csv.reader(io.StringIO(text))
        rows = list(reader)

        if len(rows) < 2:
            return jsonify({'success': False, 'error': 'CSV must have a header row and at least one data row'}), 400

        col_map = _map_columns(rows[0])
        if 'first_name' not in col_map.values():
            return jsonify({
                'success': False,
                'error': 'CSV must include a "First Name" (or "Name") column. Found columns: ' + ', '.join(h.strip() for h in rows[0] if h.strip())
            }), 400

        created = []
        errors = []
        for row_num, row in enumerate(rows[1:], start=2):
            # Build player dict from column mapping
            player_data = {}
            for col_idx, field in col_map.items():
                if col_idx < len(row):
                    val = row[col_idx].strip()
                    if val:
                        player_data[field] = val

            first_name = player_data.get('first_name', '').strip()
            last_name = player_data.get('last_name', '').strip()

            # If only "name" column mapped to first_name, try to split into first/last
            if first_name and not last_name and ' ' in first_name:
                parts = first_name.split(None, 1)
                first_name = parts[0]
                last_name = parts[1] if len(parts) > 1 else ''
                player_data['first_name'] = first_name
                player_data['last_name'] = last_name

            if not first_name:
                # Skip blank rows silently
                if any(cell.strip() for cell in row):
                    errors.append({'row': row_num, 'error': 'Missing first name'})
                continue

            if not last_name:
                errors.append({'row': row_num, 'error': f'Missing last name for "{first_name}"'})
                continue

            try:
                player = FirebaseService.create_player({
                    'first_name': first_name,
                    'last_name': last_name,
                    'date_of_birth': player_data.get('date_of_birth', ''),
                    'guardian_name': player_data.get('guardian_name', ''),
                    'guardian_email': player_data.get('guardian_email', ''),
                    'guardian_primary_phone': player_data.get('guardian_primary_phone', ''),
                    'guardian_secondary_phone': player_data.get('guardian_secondary_phone', ''),
                    'special_notes': player_data.get('special_notes', ''),
                    'team_ids': team_ids,
                })
                created.append(player)
            except Exception as e:
                logger.error("Error creating player row %d: %s", row_num, e)
                errors.append({'row': row_num, 'error': str(e)})

        return jsonify({
            'success': True,
            'created_count': len(created),
            'error_count': len(errors),
            'errors': errors[:20],  # Cap error details to avoid huge responses
            'message': f'{len(created)} player(s) created successfully' + (f', {len(errors)} error(s)' if errors else ''),
        }), 201

    except Exception as e:
        logger.exception("Error in bulk_upload_players")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500
