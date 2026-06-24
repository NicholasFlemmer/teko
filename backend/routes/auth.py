from flask import Blueprint, request, jsonify, g
import hmac as _hmac
import jwt
import logging
import os
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from config import Config
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash
from services import email_service

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)

# Fallback admin credentials from environment variables (no defaults — must be explicitly set)
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

def token_required(f):
    """Decorator to require JWT token for protected routes"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Get token from header
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]  # Bearer <token>
            except IndexError:
                return jsonify({'error': 'Invalid token format'}), 401
        
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        
        try:
            # Decode token
            data = jwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"])
            current_user = data['username']
            g.current_user_role = data.get('role')
            g.current_user_org_id = data.get('org_id')
            g.current_user_id = data.get('admin_id')
            g.current_user_email = data.get('email')
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401

        return f(current_user, *args, **kwargs)
    
    return decorated


def role_required(*allowed_roles):
    """Decorator to restrict access to specific roles. Must be used after @token_required."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user_role = getattr(g, 'current_user_role', 'admin')
            if user_role not in allowed_roles:
                return jsonify({'error': 'Insufficient permissions'}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


@auth_bp.route('/login', methods=['POST'])
def login():
    """Admin login endpoint"""
    data = request.get_json()
    
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({'error': 'Username and password required'}), 400
    
    username = data.get('username')
    password = data.get('password')

    authenticated = False
    display_name = username
    user_role = 'admin'
    org_id = None
    admin_id = None
    admin_email = None

    # First, check Firestore admin_users by email (indexed query, not full scan)
    try:
        from services.firebase_service import FirebaseService
        admin = FirebaseService.get_admin_by_email(username, include_password=True)
        pw_match = False
        if admin:
            stored_pw = admin.get('password', '')
            # Support both hashed (werkzeug) and legacy plain-text passwords
            if stored_pw.startswith(('pbkdf2:', 'scrypt:')):
                pw_match = check_password_hash(stored_pw, password)
            else:
                # Legacy plain-text: use constant-time comparison
                pw_match = _hmac.compare_digest(stored_pw, password)
        if admin and pw_match:
            # Block any non-active status (inactive, suspended, etc.)
            status = admin.get('status', 'active')
            if status != 'active':
                return jsonify({'error': f'Account is {status}'}), 401
            authenticated = True
            # Prefer an explicit name; otherwise build it from first/last name;
            # fall back to the email if neither is present.
            display_name = admin.get('name')
            if not display_name:
                full_name = f"{admin.get('first_name', '')} {admin.get('last_name', '')}".strip()
                display_name = full_name or admin.get('email') or username
            user_role = admin.get('role', 'admin')
            org_id = admin.get('org_id')
            admin_id = admin.get('id')
            admin_email = admin.get('email')
    except Exception as e:
        logger.error(f"Firestore auth lookup failed: {e}")
        # Fail closed — don't fall through to env-var credentials on Firestore errors
        return jsonify({'error': 'Authentication service unavailable'}), 503

    # Fallback to environment-variable credentials (only if explicitly configured).
    # This admin is not tied to any organisation, so org_id stays None.
    if not authenticated and ADMIN_USERNAME and ADMIN_PASSWORD and username == ADMIN_USERNAME and _hmac.compare_digest(ADMIN_PASSWORD, password):
        authenticated = True
        user_role = 'super_admin'
        org_id = None

    if authenticated:
        token = jwt.encode({
            'username': display_name,
            'role': user_role,
            'org_id': org_id,
            'admin_id': admin_id,
            'email': admin_email,
            'exp': datetime.now(timezone.utc) + timedelta(hours=Config.JWT_EXPIRY_HOURS)
        }, Config.SECRET_KEY, algorithm="HS256")

        return jsonify({
            'token': token,
            'username': display_name,
            'expires_in': Config.JWT_EXPIRY_HOURS * 3600
        }), 200

    return jsonify({'error': 'Invalid credentials'}), 401


# =============================================================================
# Password reset
#
# Admins are stored in the Firestore `admin_users` collection (not Firebase
# Auth), so we use a self-contained reset-token flow: a single-use token is
# hashed and stored on the admin's document with a short expiry, emailed to the
# user, and exchanged for a new password hash that the login route validates.
# =============================================================================

RESET_TOKEN_EXPIRY_MINUTES = 60
GENERIC_RESET_RESPONSE = {
    'message': 'If that email is registered, you will receive a reset link shortly.'
}


def _hash_reset_token(token):
    """Hash a reset token for at-rest storage (never store the raw token)."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _admin_display_name(admin):
    """Best display name for an admin: name, else first+last, else email."""
    if admin.get('name'):
        return admin['name']
    full = f"{admin.get('first_name', '')} {admin.get('last_name', '')}".strip()
    return full or admin.get('email') or 'there'


def _org_name(org_id):
    """Look up an organisation's display name, with a safe fallback."""
    if not org_id:
        return 'your organisation'
    try:
        from services.firebase_service import FirebaseService
        org = FirebaseService.get_organisation(org_id)
        if org and org.get('name'):
            return org['name']
    except Exception as e:
        logger.error("Could not load org name for %s: %s", org_id, e)
    return 'your organisation'


@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    """Start the password-reset flow.

    Always returns a generic 200 response regardless of whether the email is
    registered, to avoid leaking which accounts exist.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()

    if not email:
        return jsonify({'error': 'Email is required'}), 400

    try:
        from services.firebase_service import FirebaseService
        admin = FirebaseService.get_admin_by_email(email, include_password=True)
        if admin:
            raw_token = secrets.token_urlsafe(32)
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_EXPIRY_MINUTES)
            FirebaseService.update_admin(admin['id'], {
                'reset_token_hash': _hash_reset_token(raw_token),
                'reset_token_expires': expires_at.isoformat(),
            })
            reset_link = f"{Config.FRONTEND_URL.rstrip('/')}/reset-password?token={raw_token}"
            email_service.send_password_reset_email(email, reset_link, _admin_display_name(admin))
    except Exception as e:
        # Never surface internal errors to the caller — keep the response generic.
        logger.error("[password-reset] forgot-password failed for %s: %s", email, e)

    return jsonify(GENERIC_RESET_RESPONSE), 200


@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    """Complete the password-reset flow by exchanging a valid token for a new password."""
    data = request.get_json(silent=True) or {}
    token = (data.get('token') or '').strip()
    password = data.get('password') or ''

    if not token or not password:
        return jsonify({'error': 'Token and password are required'}), 400

    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400

    try:
        from services.firebase_service import FirebaseService
        db = FirebaseService.get_db()
        token_hash = _hash_reset_token(token)
        docs = db.collection('admin_users').where('reset_token_hash', '==', token_hash).limit(1).stream()
        admin_doc = next(iter(docs), None)

        if admin_doc is None:
            return jsonify({'error': 'Invalid or expired reset link'}), 400

        admin = admin_doc.to_dict()
        expires_raw = admin.get('reset_token_expires')
        expired = True
        if expires_raw:
            try:
                expires_at = datetime.fromisoformat(expires_raw)
                expired = datetime.now(timezone.utc) >= expires_at
            except ValueError:
                expired = True

        if expired:
            return jsonify({'error': 'Invalid or expired reset link'}), 400

        # Apply the new password and invalidate the single-use token.
        # Use pbkdf2 (not werkzeug's scrypt default) so hashing works on
        # builds without OpenSSL's scrypt; the login route accepts both.
        FirebaseService.update_admin(admin_doc.id, {
            'password': generate_password_hash(password, method='pbkdf2:sha256'),
            'reset_token_hash': None,
            'reset_token_expires': None,
        })
    except Exception as e:
        logger.error("[password-reset] reset-password failed: %s", e)
        return jsonify({'error': 'Could not reset password. Please try again.'}), 400

    return jsonify({'message': 'Password reset successfully. You can now sign in.'}), 200


# =============================================================================
# Admin invites
#
# A super admin invites a location admin by email. We store a pending invite in
# the `invites` collection with a single-use token + 48h expiry, and email a
# link. The invitee sets their name/password via the public accept-invite route,
# which creates the real admin_users document.
# =============================================================================

@auth_bp.route('/invite', methods=['POST'])
@token_required
def invite_user(current_user):
    """Invite a user to the caller's organisation.

    Super admins may invite location_admin or coach; location admins may invite
    coach only.
    """
    caller_role = getattr(g, 'current_user_role', None)
    if caller_role not in ('super_admin', 'location_admin'):
        return jsonify({'error': 'Insufficient permissions'}), 403

    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    role = (data.get('role') or '').strip()

    if not email:
        return jsonify({'error': 'Email is required'}), 400

    if caller_role == 'super_admin':
        if role not in ('location_admin', 'coach'):
            return jsonify({'error': 'Role must be location_admin or coach'}), 400
    else:  # location_admin
        if role != 'coach':
            # Location admins cannot invite other admins — only coaches.
            return jsonify({'error': 'Location admins can only invite coaches'}), 403

    try:
        from services.firebase_service import FirebaseService
        if FirebaseService.get_admin_by_email(email):
            return jsonify({'error': 'A user with that email already exists'}), 400

        org_id = getattr(g, 'current_user_org_id', None)
        invite = FirebaseService.create_admin_invite({
            'email': email,
            'role': role,
            'org_id': org_id,
            'invited_by': current_user,
        })
        invite_link = f"{Config.FRONTEND_URL.rstrip('/')}/accept-invite?token={invite['token']}"
        email_service.send_invite_email(
            email, invite_link, _org_name(org_id), current_user, role
        )
    except Exception as e:
        logger.exception("Invite failed")
        return jsonify({'error': 'Could not send invite'}), 500

    return jsonify({'message': 'Invite sent'}), 200


@auth_bp.route('/accept-invite', methods=['POST'])
def accept_invite():
    """Public endpoint: an invitee sets their name/password to create the account."""
    data = request.get_json(silent=True) or {}
    token = (data.get('token') or '').strip()
    first_name = (data.get('first_name') or '').strip()
    last_name = (data.get('last_name') or '').strip()
    password = data.get('password') or ''

    if not token or not first_name or not last_name or not password:
        return jsonify({'error': 'All fields are required'}), 400
    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400

    try:
        from services.firebase_service import FirebaseService
        db = FirebaseService.get_db()
        docs = db.collection('invites').where('token', '==', token).limit(1).stream()
        invite_doc = next(iter(docs), None)

        if invite_doc is None:
            return jsonify({'error': 'Invalid or expired invite'}), 400

        invite = invite_doc.to_dict()

        if invite.get('accepted'):
            return jsonify({'error': 'This invite has already been used'}), 400

        expires_raw = invite.get('expires_at')
        expired = True
        if expires_raw:
            try:
                expires_at = datetime.fromisoformat(expires_raw)
                expired = datetime.now(timezone.utc) >= expires_at
            except ValueError:
                expired = True
        if expired:
            return jsonify({'error': 'This invite has expired'}), 400

        FirebaseService.create_admin({
            'first_name': first_name,
            'last_name': last_name,
            'email': invite.get('email'),
            'role': invite.get('role'),
            'org_id': invite.get('org_id'),
            'password': generate_password_hash(password, method='pbkdf2:sha256'),
            'is_active': True,
        })
        invite_doc.reference.update({'accepted': True})
    except Exception as e:
        logger.exception("Accept invite failed")
        return jsonify({'error': 'Could not create account'}), 400

    # Best-effort welcome email — never fail the (already-created) account on this.
    try:
        login_url = f"{Config.FRONTEND_URL.rstrip('/')}/login"
        email_service.send_welcome_email(
            invite.get('email'),
            f"{first_name} {last_name}".strip(),
            _org_name(invite.get('org_id')),
            login_url,
        )
    except Exception as e:
        logger.error("Welcome email failed: %s", e)

    return jsonify({'message': 'Account created'}), 200


@auth_bp.route('/verify', methods=['GET'])
@token_required
def verify_token(current_user):
    """Verify if token is valid"""
    return jsonify({
        'valid': True,
        'username': current_user
    }), 200

@auth_bp.route('/refresh', methods=['POST'])
@token_required
def refresh_token(current_user):
    """Refresh JWT token, preserving the user's current role."""
    token = jwt.encode({
        'username': current_user,
        'role': getattr(g, 'current_user_role', 'admin'),
        'exp': datetime.now(timezone.utc) + timedelta(hours=Config.JWT_EXPIRY_HOURS)
    }, Config.SECRET_KEY, algorithm="HS256")

    return jsonify({
        'token': token,
        'expires_in': Config.JWT_EXPIRY_HOURS * 3600
    }), 200
