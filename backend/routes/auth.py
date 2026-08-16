from flask import Blueprint, request, jsonify, g
import hmac as _hmac
import jwt
import logging
import os
from datetime import datetime, timedelta, timezone
from config import Config
from functools import wraps
from werkzeug.security import check_password_hash

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)

# Fallback admin credentials from environment variables (no defaults — must be explicitly set)
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

# Canonical admin role vocabulary — matches the values already stored in
# Firestore admin_users. Import this rather than hardcoding role strings.
VALID_ROLES = ('super_admin', 'location_admin', 'coach')

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
            # No default role string here: a token missing a role claim must
            # fail role_required checks, not silently resolve to a working role.
            g.current_user_role = data.get('role')
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
            user_role = getattr(g, 'current_user_role', None)
            # A missing role claim must be denied explicitly, not by
            # incidentally failing the membership check below.
            if user_role is None or user_role not in allowed_roles:
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
    # No default role string: this is always overwritten before a token is
    # ever issued (or the request 401s first) — None keeps it that way rather
    # than silently carrying a working role if that ever stops being true.
    user_role = None

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
            # No default role string: a Firestore admin record with no role
            # field must issue a token that fails every role_required check,
            # not one that silently passes as a working role.
            user_role = admin.get('role')
    except Exception as e:
        logger.error(f"Firestore auth lookup failed: {e}")
        # Fail closed — don't fall through to env-var credentials on Firestore errors
        return jsonify({'error': 'Authentication service unavailable'}), 503

    # Fallback to environment-variable credentials (only if explicitly configured)
    if not authenticated and ADMIN_USERNAME and ADMIN_PASSWORD and username == ADMIN_USERNAME and _hmac.compare_digest(ADMIN_PASSWORD, password):
        authenticated = True
        user_role = VALID_ROLES[0]  # 'super_admin' — the break-glass account gets the top role

    if authenticated:
        token = jwt.encode({
            'username': display_name,
            'role': user_role,
            'exp': datetime.now(timezone.utc) + timedelta(hours=Config.JWT_EXPIRY_HOURS)
        }, Config.SECRET_KEY, algorithm="HS256")

        return jsonify({
            'token': token,
            'username': display_name,
            'expires_in': Config.JWT_EXPIRY_HOURS * 3600
        }), 200

    return jsonify({'error': 'Invalid credentials'}), 401

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
        # No default role string: token_required already denies entry here
        # if the original token had no role, so this should never fire — but
        # if it somehow does, the refreshed token must inherit that same
        # denial rather than upgrading to a working role.
        'role': getattr(g, 'current_user_role', None),
        'exp': datetime.now(timezone.utc) + timedelta(hours=Config.JWT_EXPIRY_HOURS)
    }, Config.SECRET_KEY, algorithm="HS256")

    return jsonify({
        'token': token,
        'expires_in': Config.JWT_EXPIRY_HOURS * 3600
    }), 200
