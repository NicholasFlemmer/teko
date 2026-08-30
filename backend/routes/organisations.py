import logging
import re
import zoneinfo
from flask import Blueprint, request, jsonify, g
from services.firebase_service import FirebaseService
from routes.auth import token_required, role_required

logger = logging.getLogger(__name__)

organisations_bp = Blueprint('organisations', __name__)

# Fields only a super_admin may write. location_admin is restricted to
# _SAFEGUARDING_FIELDS below -- never these, even for their own org.
_SUPER_ADMIN_ONLY_FIELDS = ['name', 'type', 'terminology', 'ai_persona_prompt', 'country', 'supported_languages']

# Org-level safeguarding configuration. Deliberately writable by
# location_admin (unlike every other org field) because a location_admin
# is the role actually running day-to-day operations at a location and is
# the realistic owner of "who is our safeguarding lead" -- super_admin can
# still write these too.
_SAFEGUARDING_FIELDS = ['safeguarding_lead_name', 'safeguarding_lead_email', 'works_with_minors']

# IANA timezone string for the org (e.g. "Africa/Johannesburg",
# "America/Sao_Paulo"). Nullable, no default. Gated the same as
# _SAFEGUARDING_FIELDS -- a location_admin is the realistic owner of "what
# timezone is this location in", same rationale as the safeguarding lead.
#
# attendance_mode: 'named' (a per-player register, the original behaviour)
# or 'headcount' (boys/girls/new-participant counts, no player documents
# required -- see ConversationService._handle_attendance_command_inner).
# Not nullable -- an absent value is read as 'named' by application code,
# so every existing org keeps today's behaviour with no backfill needed.
# Gated the same as the fields above, same rationale.
_BOTH_ROLES_FIELDS = _SAFEGUARDING_FIELDS + ['timezone', 'attendance_mode']

_VALID_ATTENDANCE_MODES = {'named', 'headcount'}

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _is_blank(value):
    """True for None, or a string that is empty/whitespace-only after
    stripping. A non-string, non-None value (e.g. a number) is deliberately
    never "blank" here -- it falls through to the type/format checks that
    follow, which reject it on its own terms rather than this helper
    silently treating it as absent.

    This is the fix for the production bug where the pair check compared
    key PRESENCE ('field' in data) instead of the field's VALUE -- the
    frontend always sends both safeguarding_lead_name/_email keys, using
    ""  for a blank field, so presence-only checking let name="Ricki" +
    email="" through as "paired" and skipped email format validation
    entirely (an empty string is falsy). Every check below must treat ""
    identically to a missing key or an explicit null.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ''
    return False


def _normalize_blank_to_none(value):
    """A blank string (or None) becomes None; anything else is trimmed if
    it's a string. Used so a field is never stored as "" -- only a real
    value or None, never an empty string, ever reaches Firestore."""
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed if trimmed else None
    return value


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


def _forbid_cross_org(scope_org_id, url_org_id):
    """None if the caller may act on url_org_id, else a 403 error response.

    scope_org_id is None only for the intentional super_admin cross-org
    case (see _resolve_org_scope) -- that caller may act on any org.
    Every other caller may only act on their own org_id. Always 403, never
    404, and identical regardless of whether url_org_id is a real
    organisation -- varying the response would tell a caller which other
    organisations exist.
    """
    if scope_org_id is None or scope_org_id == url_org_id:
        return None
    return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403


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
    """Get a single organisation by ID. Callers may only read their own
    organisation (or, for the intentional super_admin cross-org case, any)."""
    try:
        scope_org_id, err = _resolve_org_scope()
        if err:
            return err
        forbidden = _forbid_cross_org(scope_org_id, org_id)
        if forbidden:
            return forbidden

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
@role_required('super_admin', 'location_admin')
def update_organisation(current_user, org_id):
    """Update an organisation's fields.

    super_admin may write any of _SUPER_ADMIN_ONLY_FIELDS or
    _BOTH_ROLES_FIELDS. location_admin may write ONLY
    _BOTH_ROLES_FIELDS (safeguarding_lead_name, safeguarding_lead_email,
    works_with_minors, timezone, attendance_mode), and only for their own
    org -- name, type, terminology, ai_persona_prompt, country, and
    supported_languages remain super_admin-only, same as before this route
    accepted location_admin at all.

    A super_admin with an assigned org_id is still restricted to that org
    by the ownership check below -- only a super_admin with no assigned
    org (the intentional cross-org case) may update any organisation. That
    ownership check runs before any Firestore read or write, so a
    location_admin targeting another org's safeguarding fields is
    rejected with 403 without ever touching Firestore.
    """
    try:
        scope_org_id, err = _resolve_org_scope()
        if err:
            return err
        forbidden = _forbid_cross_org(scope_org_id, org_id)
        if forbidden:
            return forbidden

        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        role = getattr(g, 'current_user_role', None)
        if role == 'location_admin':
            disallowed = [field for field in data if field in _SUPER_ADMIN_ONLY_FIELDS]
            if disallowed:
                return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
            allowed_fields = _BOTH_ROLES_FIELDS
        else:
            allowed_fields = _SUPER_ADMIN_ONLY_FIELDS + _BOTH_ROLES_FIELDS

        # Pair check on VALUES, not key presence (see _is_blank docstring):
        # "" and null and an absent key are all the same "not set" state.
        name_in_data = 'safeguarding_lead_name' in data
        email_in_data = 'safeguarding_lead_email' in data
        name_has_value = name_in_data and not _is_blank(data.get('safeguarding_lead_name'))
        email_has_value = email_in_data and not _is_blank(data.get('safeguarding_lead_email'))
        if name_has_value != email_has_value:
            return jsonify({
                'success': False,
                'error': 'safeguarding_lead_name and safeguarding_lead_email must be set together'
            }), 400

        normalized_name = _normalize_blank_to_none(data.get('safeguarding_lead_name')) if name_in_data else None
        normalized_email = _normalize_blank_to_none(data.get('safeguarding_lead_email')) if email_in_data else None

        if email_has_value:
            if not isinstance(normalized_email, str) or not _EMAIL_RE.match(normalized_email):
                return jsonify({
                    'success': False,
                    'error': 'safeguarding_lead_email must be a valid email address'
                }), 400

        if 'works_with_minors' in data:
            minors_value = data['works_with_minors']
            # A bool check alone would accept "" here too, since it's
            # falsy but not a bool -- isinstance already rejects it (an
            # empty string is not a bool), so "" is a 400, never silently
            # stored. No separate blank-string carve-out needed.
            if minors_value is not None and not isinstance(minors_value, bool):
                return jsonify({
                    'success': False,
                    'error': 'works_with_minors must be true, false, or null'
                }), 400

        timezone_in_data = 'timezone' in data
        if timezone_in_data:
            timezone_value = data['timezone']
            if timezone_value is not None and not isinstance(timezone_value, str):
                return jsonify({
                    'success': False,
                    'error': 'timezone must be a string or null'
                }), 400
            # Blank ("" or whitespace-only) normalizes to None here, same as
            # the safeguarding string fields above -- it's the valid
            # "not configured" case, not an invalid value.
            normalized_timezone = _normalize_blank_to_none(timezone_value)
            # A typo used to reach Firestore unchecked and silently fall
            # back to UTC at read time (FirebaseService.get_org_now), with
            # no error surfaced to whoever saved it -- that fallback still
            # exists for data already stored before this validation shipped
            # (see get_org_now), but a new write is now checked against the
            # real IANA database so the same mistake can't happen again.
            if normalized_timezone is not None and normalized_timezone not in zoneinfo.available_timezones():
                return jsonify({
                    'success': False,
                    'error': 'timezone must be a valid IANA timezone name or null'
                }), 400

        if 'attendance_mode' in data:
            attendance_mode_value = data['attendance_mode']
            # isinstance guard first -- an unhashable value (list/dict)
            # would otherwise raise TypeError from the `in` check against
            # a set, turning an invalid request into a 500 instead of 400.
            if not isinstance(attendance_mode_value, str) or attendance_mode_value not in _VALID_ATTENDANCE_MODES:
                return jsonify({
                    'success': False,
                    'error': "attendance_mode must be 'named' or 'headcount'"
                }), 400

        org = FirebaseService.get_organisation(org_id)
        if not org:
            return jsonify({
                'success': False,
                'error': 'Organisation not found'
            }), 404

        update_data = {}
        for field in allowed_fields:
            if field not in data:
                continue
            if field == 'safeguarding_lead_name':
                update_data[field] = normalized_name
            elif field == 'safeguarding_lead_email':
                update_data[field] = normalized_email
            elif field == 'timezone':
                update_data[field] = normalized_timezone
            else:
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
    """Get just the terminology object for an organisation (with defaults).
    Callers may only read their own organisation's terminology (or, for the
    intentional super_admin cross-org case, any)."""
    try:
        scope_org_id, err = _resolve_org_scope()
        if err:
            return err
        forbidden = _forbid_cross_org(scope_org_id, org_id)
        if forbidden:
            return forbidden

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
