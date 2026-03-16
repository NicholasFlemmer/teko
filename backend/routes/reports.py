import logging
from datetime import date as _date
from flask import Blueprint, request, jsonify
from services.firebase_service import FirebaseService
from routes.auth import token_required

logger = logging.getLogger(__name__)

reports_bp = Blueprint('reports', __name__)


def _validate_date(date_str):
    """Validate date string is YYYY-MM-DD format. Returns None if invalid."""
    if not date_str:
        return None
    try:
        _date.fromisoformat(date_str)
        return date_str
    except (ValueError, TypeError):
        return None

@reports_bp.route('/coach-attendance', methods=['GET'])
@token_required
def get_coach_attendance(current_user):
    """Get coach attendance data with optional date range"""
    try:
        start_date = _validate_date(request.args.get('start_date'))
        end_date = _validate_date(request.args.get('end_date'))

        # Get sessions in date range
        if start_date and end_date:
            sessions = FirebaseService.get_sessions_by_date_range(start_date, end_date)
        else:
            sessions = FirebaseService.get_all_sessions(start_date=start_date, end_date=end_date)

        coaches = FirebaseService.get_all_coaches()
        coach_map = {c['id']: c for c in coaches}

        # Aggregate by coach
        coach_data = {}
        for s in sessions:
            cids = FirebaseService.get_session_coach_ids(s)
            for cid in cids:
                if cid not in coach_data:
                    coach = coach_map.get(cid, {})
                    coach_name = coach.get('name') or (
                        (coach.get('first_name', '') + ' ' + coach.get('last_name', '')).strip()
                    ) or 'Unknown'
                    coach_data[cid] = {
                        'coach_id': cid,
                        'coach_name': coach_name,
                        'total_sessions': 0,
                        'checked_in': 0,
                    }
                coach_data[cid]['total_sessions'] += 1
                if s.get('status') in ('checked_in', 'completed'):
                    coach_data[cid]['checked_in'] += 1

        data = list(coach_data.values())

        return jsonify({
            'success': True,
            'data': data
        }), 200
    except Exception as e:
        logger.exception("Error in get_coach_attendance")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@reports_bp.route('/location-attendance', methods=['GET'])
@token_required
def get_location_attendance(current_user):
    """Get location attendance data with optional date range"""
    try:
        start_date = _validate_date(request.args.get('start_date'))
        end_date = _validate_date(request.args.get('end_date'))

        if start_date and end_date:
            sessions = FirebaseService.get_sessions_by_date_range(start_date, end_date)
        else:
            sessions = FirebaseService.get_all_sessions(start_date=start_date, end_date=end_date)

        locations = FirebaseService.get_all_locations()
        location_map = {l['id']: l for l in locations}

        # Aggregate by location
        location_data = {}
        for s in sessions:
            lid = s.get('location_id')
            if not lid:
                continue
            if lid not in location_data:
                loc = location_map.get(lid, {})
                location_data[lid] = {
                    'location_id': lid,
                    'location_name': loc.get('name', 'Unknown'),
                    'total_sessions': 0,
                    'checked_in': 0,
                }
            location_data[lid]['total_sessions'] += 1
            if s.get('status') in ('checked_in', 'completed'):
                location_data[lid]['checked_in'] += 1

        data = list(location_data.values())

        return jsonify({
            'success': True,
            'data': data
        }), 200
    except Exception as e:
        logger.exception("Error in get_location_attendance")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@reports_bp.route('/student-rollcall', methods=['GET'])
@token_required
def get_student_rollcall(current_user):
    """Get student participation / roll call data using attended_player_ids"""
    try:
        start_date = _validate_date(request.args.get('start_date'))
        end_date = _validate_date(request.args.get('end_date'))

        # Get sessions in date range
        if start_date and end_date:
            sessions = FirebaseService.get_sessions_by_date_range(start_date, end_date)
        else:
            sessions = FirebaseService.get_all_sessions(start_date=start_date, end_date=end_date)

        # Get all players
        players = FirebaseService.get_all_players()
        teams = FirebaseService.get_all_teams()
        team_map = {t['id']: t for t in teams}

        # For each player, count how many sessions they appear in attended_player_ids
        # and how many sessions their team was involved in (eligible sessions)
        rollcall = []
        for p in players:
            player_team_ids = p.get('team_ids', [])

            # Sessions where this player's team was involved
            eligible_sessions = [
                s for s in sessions
                if s.get('team_id') in player_team_ids
            ]
            total_eligible = len(eligible_sessions)

            # Sessions where the player actually attended
            attended = sum(
                1 for s in eligible_sessions
                if p['id'] in s.get('attended_player_ids', [])
            )

            absent = total_eligible - attended
            rate = round((attended / total_eligible) * 100) if total_eligible > 0 else 0

            player_teams = [team_map.get(tid, {}).get('name', 'Unknown') for tid in player_team_ids]

            rollcall.append({
                'player_id': p['id'],
                'player_name': (p.get('first_name', '') + ' ' + p.get('last_name', '')).strip(),
                'teams': player_teams,
                'total_sessions': total_eligible,
                'attended': attended,
                'absent': absent,
                'attendance_rate': rate,
            })

        return jsonify({
            'success': True,
            'data': rollcall
        }), 200
    except Exception as e:
        logger.exception("Error in get_student_rollcall")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@reports_bp.route('/stats', methods=['GET'])
@token_required
def get_stats(current_user):
    """Get quick stats: total sessions, check-in rate, students, active coaches"""
    try:
        sessions = FirebaseService.get_all_sessions()
        total_sessions = len(sessions)
        checked_in_count = sum(1 for s in sessions if s.get('status') in ('checked_in', 'completed'))
        check_in_rate = round((checked_in_count / total_sessions) * 100) if total_sessions > 0 else 0

        total_students = FirebaseService.count_players()
        active_coaches = FirebaseService.count_active_coaches()

        stats = {
            'total_sessions': total_sessions,
            'check_in_rate': check_in_rate,
            'total_students': total_students,
            'active_coaches': active_coaches,
        }

        return jsonify({
            'success': True,
            'stats': stats
        }), 200
    except Exception as e:
        logger.exception("Error in get_stats")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500
