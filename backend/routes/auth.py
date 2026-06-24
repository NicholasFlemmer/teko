from flask import Blueprint, request, jsonify, g
import hmac as _hmac
import jwt
import logging
import os
import secrets
import hashlib
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone
from config import Config
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash

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
            display_name = admin.get('name', username)
            user_role = admin.get('role', 'admin')
            org_id = admin.get('org_id')
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


def _send_reset_email(to_email, reset_link):
    """Send the password-reset email via SMTP.

    Falls back to logging the link to the console when SMTP env vars are not
    configured, so the flow works locally without an email provider.
    """
    smtp_host = os.environ.get('SMTP_HOST')
    smtp_port = os.environ.get('SMTP_PORT', '587')
    smtp_user = os.environ.get('SMTP_USER')
    smtp_password = os.environ.get('SMTP_PASSWORD')
    smtp_from = os.environ.get('SMTP_FROM', smtp_user)

    if not smtp_host or not smtp_from:
        # Logged at WARNING so it's visible without extra logging config — this
        # is the local-dev fallback when no SMTP provider is configured.
        logger.warning("[password-reset] SMTP not configured — reset link for %s: %s", to_email, reset_link)
        return

    msg = EmailMessage()
    msg['Subject'] = 'Reset your Teko password'
    msg['From'] = smtp_from
    msg['To'] = to_email
    msg.set_content(
        "We received a request to reset your Teko password.\n\n"
        f"Use the link below to set a new password (valid for {RESET_TOKEN_EXPIRY_MINUTES} minutes):\n\n"
        f"{reset_link}\n\n"
        "If you didn't request this, you can safely ignore this email."
    )

    try:
        with smtplib.SMTP(smtp_host, int(smtp_port)) as server:
            server.starttls()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.send_message(msg)
        logger.info("[password-reset] Sent reset email to %s", to_email)
    except Exception as e:
        logger.error("[password-reset] Failed to send reset email to %s: %s", to_email, e)


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
            _send_reset_email(email, reset_link)
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
