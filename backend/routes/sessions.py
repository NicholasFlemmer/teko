import logging
from flask import Blueprint, request, jsonify
from services.firebase_service import FirebaseService
from services.whatsapp_service import WhatsAppService
from routes.auth import token_required
from utils.geolocation import verify_location, format_location
from utils.phone import normalize_sa_phone
from datetime import datetime, timedelta, timezone, date as _date
from config import Config
import uuid
import calendar
import re

logger = logging.getLogger(__name__)

sessions_bp = Blueprint('sessions', __name__)


def _generate_recurrence_dates(start, end, frequency):
    """Generate a list of dates from start to end based on frequency."""
    dates = []
    current = start
    while current <= end:
        dates.append(current)
        if frequency == 'weekly':
            current += timedelta(weeks=1)
        elif frequency == 'biweekly':
            current += timedelta(weeks=2)
        elif frequency == 'monthly':
            # Advance by one month, clamp day to valid range
            month = current.month + 1
            year = current.year
            if month > 12:
                month = 1
                year += 1
            day = min(current.day, calendar.monthrange(year, month)[1])
            current = _date(year, month, day)
    return dates

@sessions_bp.route('', methods=['GET'])
@token_required
def get_sessions(current_user):
    """Get all sessions with optional filters"""
    try:
        # Get query parameters
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        coach_id = request.args.get('coach_id')
        
        sessions = FirebaseService.get_all_sessions(
            start_date=start_date,
            end_date=end_date,
            coach_id=coach_id
        )
        
        return jsonify({
            'success': True,
            'sessions': sessions
        }), 200
    except Exception as e:
        logger.exception("Error in get_sessions")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@sessions_bp.route('/<session_id>', methods=['GET'])
@token_required
def get_session(current_user, session_id):
    """Get a specific session by ID"""
    try:
        session = FirebaseService.get_session(session_id)
        if not session:
            return jsonify({
                'success': False,
                'error': 'Session not found'
            }), 404
        
        return jsonify({
            'success': True,
            'session': session
        }), 200
    except Exception as e:
        logger.exception("Error in get_session")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@sessions_bp.route('', methods=['POST'])
@token_required
def create_session(current_user):
    """Create a new session"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        # Validate required fields - only date and start_time are truly required
        if 'date' not in data or 'start_time' not in data:
            return jsonify({
                'success': False,
                'error': 'Missing required fields: date and start_time'
            }), 400

        # Validate date format
        try:
            _date.fromisoformat(data['date'])
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid date format. Use YYYY-MM-DD'}), 400

        # Validate time format (HH:MM) with valid hour/minute ranges
        try:
            datetime.strptime(data['start_time'], '%H:%M')
        except ValueError:
            return jsonify({'success': False, 'error': 'Invalid start_time format. Use HH:MM (00-23:00-59)'}), 400

        # Build session data
        # Support coach_ids (array) or coach_id (string, backward compat)
        coach_ids = data.get('coach_ids', [])
        if not coach_ids and data.get('coach_id'):
            coach_ids = [data['coach_id']]

        session_data = {
            'date': data['date'],
            'start_time': data['start_time'],
            'end_time': data.get('end_time', ''),
            'coach_ids': coach_ids,
            'coach_id': coach_ids[0] if coach_ids else '',
            'address': data.get('address', ''),
        }

        # Handle location - can be lat/lng object or location_id
        if 'location' in data and isinstance(data['location'], dict):
            location = data['location']
            if 'latitude' in location and 'longitude' in location:
                session_data['location'] = format_location(location['latitude'], location['longitude'])
        elif 'location_id' in data:
            session_data['location_id'] = data['location_id']

        # Optional new fields
        optional_fields = ['team_id', 'type', 'notes', 'location_id']
        for field in optional_fields:
            if field in data:
                session_data[field] = data[field]

        # Handle recurrence
        recurrence = data.get('recurrence')
        if recurrence:
            frequency = recurrence.get('frequency', 'weekly')
            end_date_str = recurrence.get('end_date')
            if not end_date_str:
                return jsonify({'success': False, 'error': 'recurrence.end_date is required'}), 400
            if frequency not in ('weekly', 'biweekly', 'monthly'):
                return jsonify({'success': False, 'error': 'frequency must be weekly, biweekly, or monthly'}), 400

            start = _date.fromisoformat(data['date'])
            end = _date.fromisoformat(end_date_str)
            if end <= start:
                return jsonify({'success': False, 'error': 'end_date must be after session date'}), 400

            group_id = str(uuid.uuid4())
            dates = _generate_recurrence_dates(start, end, frequency)
            if len(dates) > 52:
                dates = dates[:52]

            created_sessions = []
            for d in dates:
                s = dict(session_data)
                s['date'] = d.isoformat()
                s['recurrence_group_id'] = group_id
                s['recurrence'] = {'frequency': frequency, 'end_date': end_date_str}
                created = FirebaseService.create_session(s)
                created_sessions.append(created)

            return jsonify({
                'success': True,
                'sessions': created_sessions,
                'recurrence_group_id': group_id,
                'message': f'{len(created_sessions)} recurring sessions created'
            }), 201

        # Create single session
        session = FirebaseService.create_session(session_data)

        return jsonify({
            'success': True,
            'session': session,
            'message': 'Session created successfully'
        }), 201
    except Exception as e:
        logger.exception("Error in create_session")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@sessions_bp.route('/<session_id>', methods=['PUT'])
@token_required
def update_session(current_user, session_id):
    """Update a session"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        # Check if session exists
        session = FirebaseService.get_session(session_id)
        if not session:
            return jsonify({
                'success': False,
                'error': 'Session not found'
            }), 404
        
        # Update allowed fields
        update_data = {}
        allowed_fields = ['date', 'start_time', 'end_time', 'coach_id', 'coach_ids', 'location', 'address',
                          'status', 'team_id', 'type', 'notes', 'location_id']

        for field in allowed_fields:
            if field in data:
                if field == 'coach_ids':
                    update_data['coach_ids'] = data['coach_ids']
                    update_data['coach_id'] = data['coach_ids'][0] if data['coach_ids'] else ''
                    continue
                if field == 'coach_id' and 'coach_ids' in data:
                    continue  # coach_ids takes precedence

                if field == 'location':
                    location = data['location']
                    if not isinstance(location, dict) or 'latitude' not in location or 'longitude' not in location:
                        return jsonify({
                            'success': False,
                            'error': 'Location must be an object with latitude and longitude'
                        }), 400
                    update_data[field] = format_location(location['latitude'], location['longitude'])
                else:
                    update_data[field] = data[field]
        
        if not update_data:
            return jsonify({
                'success': False,
                'error': 'No valid fields to update'
            }), 400

        scope = request.args.get('scope', 'single')
        if scope not in ('single', 'future', 'all'):
            return jsonify({'success': False, 'error': 'scope must be single, future, or all'}), 400
        group_id = session.get('recurrence_group_id')

        if scope in ('future', 'all') and group_id:
            # Bulk update: don't change per-session 'date' field
            bulk_data = {k: v for k, v in update_data.items() if k != 'date'}
            group_sessions = FirebaseService.get_sessions_by_recurrence_group(group_id)
            updated_count = 0
            for s in group_sessions:
                if scope == 'all' or s.get('date', '') >= session.get('date', ''):
                    FirebaseService.update_session(s['id'], bulk_data)
                    updated_count += 1
            return jsonify({
                'success': True,
                'message': f'{updated_count} session(s) updated'
            }), 200

        # Update single session
        updated_session = FirebaseService.update_session(session_id, update_data)

        return jsonify({
            'success': True,
            'session': updated_session,
            'message': 'Session updated successfully'
        }), 200
    except Exception as e:
        logger.exception("Error in update_session")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@sessions_bp.route('/<session_id>', methods=['DELETE'])
@token_required
def delete_session(current_user, session_id):
    """Delete a session.

    Query params:
        scope: single (default) | future | all
            - single: delete only this session
            - future: delete this session and all future sessions in the recurrence group
            - all: delete all sessions in the recurrence group
    """
    try:
        session = FirebaseService.get_session(session_id)
        if not session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404

        scope = request.args.get('scope', 'single')
        if scope not in ('single', 'future', 'all'):
            return jsonify({'success': False, 'error': 'scope must be single, future, or all'}), 400
        group_id = session.get('recurrence_group_id')

        if scope in ('future', 'all') and group_id:
            group_sessions = FirebaseService.get_sessions_by_recurrence_group(group_id)
            deleted = 0
            for s in group_sessions:
                if scope == 'all' or s.get('date', '') >= session.get('date', ''):
                    FirebaseService.delete_session(s['id'])
                    deleted += 1
            return jsonify({
                'success': True,
                'message': f'{deleted} session(s) deleted'
            }), 200

        FirebaseService.delete_session(session_id)
        return jsonify({'success': True, 'message': 'Session deleted successfully'}), 200
    except Exception as e:
        logger.exception("Error in delete_session")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500

@sessions_bp.route('/<session_id>/send-reminder', methods=['POST'])
@token_required
def send_reminder(current_user, session_id):
    """Manually send reminder for a session"""
    try:
        # Get session
        session = FirebaseService.get_session(session_id)
        if not session:
            return jsonify({
                'success': False,
                'error': 'Session not found'
            }), 404
        
        # Get all coaches for this session
        coach_ids = FirebaseService.get_session_coach_ids(session)
        if not coach_ids:
            return jsonify({
                'success': False,
                'error': 'No coach assigned to this session'
            }), 400

        # Resolve location — maps link is source of truth
        location_address = ''
        location_id = session.get('location_id')
        if location_id:
            loc = FirebaseService.get_location(location_id)
            if loc:
                lat = loc.get('latitude')
                lng = loc.get('longitude')
                loc_name = loc.get('name', '')
                if lat is not None and lng is not None:
                    maps_link = f"https://maps.google.com/?q={lat},{lng}"
                    location_address = f"{loc_name} {maps_link}".strip() if loc_name else maps_link
                else:
                    location_address = loc_name or loc.get('address', '')
        if not location_address:
            location_address = session.get('address', '') or 'TBC'

        results = []
        for cid in coach_ids:
            coach = FirebaseService.get_coach(cid)
            if not coach:
                results.append({'coach_id': cid, 'error': 'Coach not found'})
                continue

            coach_name = coach.get('name') or f"{coach.get('first_name', '')} {coach.get('last_name', '')}".strip() or 'Coach'
            phone = normalize_sa_phone(coach.get('phone_number', ''))
            if not phone:
                results.append({'coach_id': cid, 'error': f'Invalid phone for {coach_name}'})
                continue

            token = str(uuid.uuid4())
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=Config.CHECK_IN_TOKEN_EXPIRY_MINUTES)
            FirebaseService.create_check_in_token(token, session_id, expires_at)
            check_in_url = f"{Config.FRONTEND_URL}/check-in/{token}"

            result = WhatsAppService.send_check_in_reminder(
                coach_phone=phone,
                coach_name=coach_name,
                session_time=session.get('start_time', ''),
                location_address=location_address,
                check_in_url=check_in_url
            )
            results.append({'coach_id': cid, 'coach_name': coach_name, **result})

        # Update session status only if at least one reminder succeeded
        if any(r.get('success') for r in results):
            FirebaseService.update_session(session_id, {'status': 'reminded'})

        return jsonify({
            'success': True,
            'message': f'Reminder sent to {len(coach_ids)} coach(es)',
            'results': results
        }), 200
    except Exception as e:
        logger.exception("Error in send_reminder")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@sessions_bp.route('/<session_id>/attendance', methods=['GET'])
@token_required
def get_attendance(current_user, session_id):
    """Get attendance for a session"""
    try:
        session = FirebaseService.get_session(session_id)
        if not session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404

        attended_player_ids = session.get('attended_player_ids', [])
        return jsonify({
            'success': True,
            'attended_player_ids': attended_player_ids
        }), 200
    except Exception as e:
        logger.exception("Error in get_attendance")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500

@sessions_bp.route('/<session_id>/attendance', methods=['PUT'])
@token_required
def update_attendance(current_user, session_id):
    """Update attendance for a session - set which players attended"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400
        session = FirebaseService.get_session(session_id)
        if not session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404

        attended_player_ids = data.get('attended_player_ids', [])
        updated = FirebaseService.update_session(session_id, {
            'attended_player_ids': attended_player_ids
        })

        return jsonify({
            'success': True,
            'session': updated,
            'message': 'Attendance updated successfully'
        }), 200
    except Exception as e:
        logger.exception("Error in update_attendance")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500

@sessions_bp.route('/check-in/<token>', methods=['GET'])
def get_check_in_info(token):
    """Get check-in information for a token (public endpoint)"""
    try:
        # Get token from database
        token_data = FirebaseService.get_check_in_token(token)
        
        if not token_data:
            return jsonify({
                'success': False,
                'error': 'Invalid check-in token'
            }), 404
        
        # Check if token is used
        if token_data.get('used'):
            return jsonify({
                'success': False,
                'error': 'This check-in link has already been used'
            }), 400
        
        # Check if token is expired
        expires_at = token_data.get('expires_at')
        if expires_at:
            # Convert to naive datetime if it's timezone-aware (from Firestore)
            if hasattr(expires_at, 'tzinfo') and expires_at.tzinfo is not None:
                expires_at = expires_at.replace(tzinfo=None)
            if datetime.now(timezone.utc) > expires_at:
                return jsonify({
                    'success': False,
                    'error': 'This check-in link has expired'
                }), 400
        
        # Get session details
        session_id = token_data.get('session_id')
        session = FirebaseService.get_session(session_id)
        
        if not session:
            return jsonify({
                'success': False,
                'error': 'Session not found'
            }), 404
        
        # Get coach details
        coach_id = session.get('coach_id')
        coach = FirebaseService.get_coach(coach_id) if coach_id else None
        coach_name = 'Unknown'
        if coach:
            coach_name = coach.get('name') or f"{coach.get('first_name', '')} {coach.get('last_name', '')}".strip() or 'Unknown'

        # Resolve location from location_id
        location_data = {}
        address = session.get('address', '')
        location_id = session.get('location_id')
        if location_id:
            location_record = FirebaseService.get_location(location_id)
            if location_record:
                address = location_record.get('address', address)
                lat = location_record.get('latitude')
                lng = location_record.get('longitude')
                if lat is not None and lng is not None:
                    location_data = {'latitude': float(lat), 'longitude': float(lng)}

        return jsonify({
            'success': True,
            'session': {
                'id': session_id,
                'date': session.get('date', ''),
                'start_time': session.get('start_time', ''),
                'end_time': session.get('end_time', ''),
                'address': address,
                'location': location_data
            },
            'coach': {
                'name': coach_name
            }
        }), 200
    except Exception as e:
        logger.exception("Error in get_check_in_info")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@sessions_bp.route('/check-in/<token>', methods=['POST'])
def check_in(token):
    """Check in for a session (public endpoint)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        # Validate location data
        if 'location' not in data or not isinstance(data['location'], dict) or 'latitude' not in data['location'] or 'longitude' not in data['location']:
            return jsonify({
                'success': False,
                'error': 'Location data required (latitude and longitude)'
            }), 400
        
        # Get token from database
        token_data = FirebaseService.get_check_in_token(token)
        
        if not token_data:
            return jsonify({
                'success': False,
                'error': 'Invalid check-in token'
            }), 404
        
        # Check if token is used
        if token_data.get('used'):
            return jsonify({
                'success': False,
                'error': 'This check-in link has already been used'
            }), 400
        
        # Check if token is expired
        expires_at = token_data.get('expires_at')
        if expires_at:
            # Convert to naive datetime if it's timezone-aware (from Firestore)
            if hasattr(expires_at, 'tzinfo') and expires_at.tzinfo is not None:
                expires_at = expires_at.replace(tzinfo=None)
            if datetime.now(timezone.utc) > expires_at:
                return jsonify({
                    'success': False,
                    'error': 'This check-in link has expired'
                }), 400
        
        # Get session
        session_id = token_data.get('session_id')
        session = FirebaseService.get_session(session_id)
        
        if not session:
            return jsonify({
                'success': False,
                'error': 'Session not found'
            }), 404
        
        # Verify location
        actual_location = format_location(
            data['location']['latitude'],
            data['location']['longitude']
        )

        # Resolve expected location coordinates from location_id
        expected_location = {}
        allowed_radius = Config.GEOLOCATION_RADIUS_METERS
        location_id = session.get('location_id')
        if location_id:
            location_record = FirebaseService.get_location(location_id)
            if location_record:
                lat = location_record.get('latitude')
                lng = location_record.get('longitude')
                if lat is not None and lng is not None:
                    expected_location = {'latitude': float(lat), 'longitude': float(lng)}
                # Use per-location radius if set
                loc_radius = location_record.get('radius')
                if loc_radius is not None:
                    allowed_radius = int(loc_radius)

        location_verification = verify_location(actual_location, expected_location, allowed_radius)
        
        # Mark token as used
        FirebaseService.mark_token_used(token)
        
        # Update session with check-in data
        check_in_data = {
            'location': actual_location,
            'location_verified': location_verification['within_radius'],
            'distance': location_verification.get('distance')
        }
        
        updated_session = FirebaseService.check_in_session(session_id, check_in_data)
        
        return jsonify({
            'success': True,
            'message': 'Check-in successful',
            'session': updated_session,
            'location_verification': location_verification
        }), 200
    except Exception as e:
        logger.exception("Error in check_in")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500
