import logging
import re
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

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


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
    _SAFEGUARDING_FIELDS. location_admin may write ONLY
    _SAFEGUARDING_FIELDS (safeguarding_lead_name, safeguarding_lead_email,
    works_with_minors), and only for their own org -- name, type,
    terminology, ai_persona_prompt, country, and supported_languages
    remain super_admin-only, same as before this route accepted
    location_admin at all.

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
            allowed_fields = _SAFEGUARDING_FIELDS
        else:
            allowed_fields = _SUPER_ADMIN_ONLY_FIELDS + _SAFEGUARDING_FIELDS

        has_lead_name = 'safeguarding_lead_name' in data
        has_lead_email = 'safeguarding_lead_email' in data
        if has_lead_name != has_lead_email:
            return jsonify({
                'success': False,
                'error': 'safeguarding_lead_name and safeguarding_lead_email must be set together'
            }), 400

        if has_lead_email and data['safeguarding_lead_email'] is not None:
            email_value = data['safeguarding_lead_email']
            if not isinstance(email_value, str) or not _EMAIL_RE.match(email_value):
                return jsonify({
                    'success': False,
                    'error': 'safeguarding_lead_email must be a valid email address'
                }), 400

        if 'works_with_minors' in data:
            minors_value = data['works_with_minors']
            if minors_value is not None and not isinstance(minors_value, bool):
                return jsonify({
                    'success': False,
                    'error': 'works_with_minors must be true, false, or null'
                }), 400

        org = FirebaseService.get_organisation(org_id)
        if not org:
            return jsonify({
                'success': False,
                'error': 'Organisation not found'
            }), 404

        update_data = {}
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
