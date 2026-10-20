import logging
from datetime import date as _date, datetime as _datetime
from flask import Blueprint, request, jsonify, g
from services.firebase_service import FirebaseService
from routes.auth import token_required

logger = logging.getLogger(__name__)

reports_bp = Blueprint('reports', __name__)


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


def _validate_date(date_str):
    """Validate date string is YYYY-MM-DD format. Returns None if invalid."""
    if not date_str:
        return None
    try:
        _date.fromisoformat(date_str)
        return date_str
    except (ValueError, TypeError):
        return None


def _sessions_in_range(org_id, start_date, end_date):
    if start_date and end_date:
        return FirebaseService.get_sessions_by_date_range(org_id, start_date, end_date)
    return FirebaseService.get_all_sessions(org_id, start_date=start_date, end_date=end_date)


def _has_started(session, now):
    """True when the session's start (org-local wall clock) is at or before
    `now`. A missing/odd start_time counts as the start of that day."""
    date_str = session.get('date')
    if not date_str:
        return False
    start = (session.get('start_time') or '00:00')[:5]
    try:
        return _datetime.strptime(f"{date_str} {start}", '%Y-%m-%d %H:%M') <= now
    except (ValueError, TypeError):
        try:
            return _datetime.strptime(date_str, '%Y-%m-%d') <= now
        except (ValueError, TypeError):
            return False


def _countable_sessions(sessions, now):
    """Sessions that belong in an attendance rate: already started, and not
    cancelled. Future and cancelled sessions can't have been checked in to,
    so they must not sit in the denominator."""
    return [s for s in sessions if s.get('status') != 'cancelled' and _has_started(s, now)]


def _is_checked_in(session):
    return session.get('status') in ('checked_in', 'completed')


def _check_in_verified(session, coach_id=None):
    """Whether a checked-in session's location was verified. With coach_id,
    that coach's own check-in is used when it was recorded; otherwise every
    recorded coach check-in must be verified. A legacy non-dict marker counts
    as verified; no per-coach record falls back to the session-level flag."""
    entries = session.get('coach_check_ins') or {}
    if coach_id is not None and coach_id in entries:
        entries = {coach_id: entries[coach_id]}
    if entries:
        return all(
            bool(v.get('location_verified')) if isinstance(v, dict) else True
            for v in entries.values()
        )
    return bool(session.get('location_verified'))


def _tally_check_in(row, session, coach_id=None):
    """Add one counted session to a row's total/checked-in/verified counters."""
    row['total_sessions'] += 1
    if _is_checked_in(session):
        row['checked_in'] += 1
        if _check_in_verified(session, coach_id):
            row['verified_check_ins'] += 1
        else:
            row['unverified_check_ins'] += 1


def _new_row(**fields):
    return {**fields, 'total_sessions': 0, 'checked_in': 0,
            'verified_check_ins': 0, 'unverified_check_ins': 0}

@reports_bp.route('/coach-attendance', methods=['GET'])
@token_required
def get_coach_attendance(current_user):
    """Get coach attendance data with optional date range"""
    try:
        org_id, err = _resolve_org_scope()
        if err:
            return err

        start_date = _validate_date(request.args.get('start_date'))
        end_date = _validate_date(request.args.get('end_date'))

        now = FirebaseService.get_org_now(org_id)
        sessions = _countable_sessions(_sessions_in_range(org_id, start_date, end_date), now)

        coaches = FirebaseService.get_all_coaches(org_id)
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
                    coach_data[cid] = _new_row(coach_id=cid, coach_name=coach_name)
                _tally_check_in(coach_data[cid], s, coach_id=cid)

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
        org_id, err = _resolve_org_scope()
        if err:
            return err

        start_date = _validate_date(request.args.get('start_date'))
        end_date = _validate_date(request.args.get('end_date'))

        now = FirebaseService.get_org_now(org_id)
        sessions = _countable_sessions(_sessions_in_range(org_id, start_date, end_date), now)

        locations = FirebaseService.get_all_locations(org_id)
        location_map = {l['id']: l for l in locations}

        # Aggregate by location
        location_data = {}
        for s in sessions:
            lid = s.get('location_id')
            if not lid:
                continue
            if lid not in location_data:
                loc = location_map.get(lid, {})
                location_data[lid] = _new_row(location_id=lid, location_name=loc.get('name', 'Unknown'))
            _tally_check_in(location_data[lid], s)

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
        org_id, err = _resolve_org_scope()
        if err:
            return err

        start_date = _validate_date(request.args.get('start_date'))
        end_date = _validate_date(request.args.get('end_date'))

        now = FirebaseService.get_org_now(org_id)
        sessions = _countable_sessions(_sessions_in_range(org_id, start_date, end_date), now)

        # Get all players
        players = FirebaseService.get_all_players(org_id)
        teams = FirebaseService.get_all_teams(org_id)
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
    """Get quick stats: started sessions, check-in rate (with verified split),
    students enrolled / headcount recorded, active coaches. Optional date range."""
    try:
        org_id, err = _resolve_org_scope()
        if err:
            return err

        start_date = _validate_date(request.args.get('start_date'))
        end_date = _validate_date(request.args.get('end_date'))

        now = FirebaseService.get_org_now(org_id)
        in_range = _sessions_in_range(org_id, start_date, end_date)
        sessions = _countable_sessions(in_range, now)

        total_sessions = len(sessions)
        checked_in_sessions = [s for s in sessions if _is_checked_in(s)]
        checked_in_count = len(checked_in_sessions)
        verified_count = sum(1 for s in checked_in_sessions if _check_in_verified(s))
        check_in_rate = round((checked_in_count / total_sessions) * 100) if total_sessions > 0 else 0

        org = FirebaseService.get_organisation(org_id) if org_id else None
        attendance_mode = 'headcount' if (org or {}).get('attendance_mode') == 'headcount' else 'named'
        total_headcount = sum(
            (s.get('headcount') or {}).get('total', 0) or 0
            for s in in_range if s.get('status') != 'cancelled'
        )

        total_students = FirebaseService.count_players(org_id)
        active_coaches = FirebaseService.count_active_coaches(org_id)

        stats = {
            'total_sessions': total_sessions,
            'check_in_rate': check_in_rate,
            'checked_in': checked_in_count,
            'verified_check_ins': verified_count,
            'unverified_check_ins': checked_in_count - verified_count,
            'attendance_mode': attendance_mode,
            'total_headcount': total_headcount,
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
