from flask import Blueprint, request, jsonify, g
import hmac as _hmac
import jwt
import logging
import os
from datetime import datetime, timedelta, timezone
from config import Config
from functools import wraps
from werkzeug.security import check_password_hash
from services.rate_limiter import is_rate_limited
from utils.request_ip import get_trusted_client_ip

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)

# Fallback admin credentials from environment variables (no defaults — must be explicitly set)
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

# Real usage is ~12 login attempts across 48h for 7 accounts, so both of
# these are deliberately tight. Per-email: 5 attempts / 15 min covers a
# legitimate user mistyping their password a few times in a row (and
# resets fast enough not to lock anyone out for long) while capping
# sustained online guessing against one account to 480/day. Per-IP: 20
# attempts / 15 min is looser than per-email since one IP can be several
# of the 7 admins on the same office network, but still caps how much an
# attacker can spread across many guessed/enumerated emails from one
# source. Both apply together (see login()) so neither alone is the only
# thing standing between an attacker and unlimited attempts.
LOGIN_EMAIL_RATE_LIMIT = (5, 15 * 60)  # (max_count, window_seconds)
LOGIN_IP_RATE_LIMIT = (20, 15 * 60)

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

            # Fail closed on org_id, the same way: a token minted before
            # org_id was wired into login() -- or any hand-crafted/forged
            # token -- has no 'org_id' claim key at all, and must be denied
            # outright rather than letting current_user_org_id silently
            # resolve to None, which _resolve_org_scope() elsewhere treats
            # as a legitimate cross-org read.
            #
            # EXCEPTION: super_admin is the Triggr platform role and
            # legitimately operates across organisations. login() now
            # always issues an 'org_id' claim for every role, using
            # whatever value is on the admin_users record -- for a
            # super_admin with no assigned org that's an explicit
            # `org_id: null` claim (present, not missing). The only way a
            # super_admin token reaches this branch at all is a token
            # minted before this change, which never had the key -- and
            # since super_admin already had unrestricted cross-org access
            # before this change, granting it here (org_id=None, same
            # value _resolve_org_scope() already treats as the intentional
            # super_admin cross-org case) is a no-op for that role, not a
            # widening of access.
            if 'org_id' not in data and g.current_user_role != 'super_admin':
                return jsonify({'error': 'Token missing organisation context'}), 401
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

    # Rate limit BEFORE any Firestore admin lookup, and return the exact
    # same response either way this fires -- the response must not reveal
    # whether `username` is a real account. Checked (and recorded) even for
    # a made-up email: an attacker enumerating emails is still making
    # attempts against this endpoint and must still be throttled.
    #
    # get_trusted_client_ip() only ever returns Google's own appended
    # second-to-last X-Forwarded-For entry (or the fixed UNRESOLVED_IP_KEY
    # sentinel), never the attacker-suppliable first entry -- see
    # utils/request_ip.py. remote_addr fallback is opt-in via Config.DEBUG
    # (local dev only, no Google front end in front of the process); it
    # must never be used on Cloud Run, where it resolves to the GFE's own
    # IP shared by every real user.
    client_ip = get_trusted_client_ip(request.headers, remote_addr=request.remote_addr, allow_remote_addr_fallback=Config.DEBUG)
    email_rate_limited = is_rate_limited(f"login:email:{username.strip().lower()}", *LOGIN_EMAIL_RATE_LIMIT)
    ip_rate_limited = is_rate_limited(f"login:ip:{client_ip}", *LOGIN_IP_RATE_LIMIT)
    if email_rate_limited or ip_rate_limited:
        return jsonify({'error': 'Too many login attempts. Please try again later.'}), 429

    authenticated = False
    display_name = username
    # No default role string: this is always overwritten before a token is
    # ever issued (or the request 401s first) — None keeps it that way rather
    # than silently carrying a working role if that ever stops being true.
    user_role = None
    # No default org: mirrors user_role above. Stays None for the env-var
    # break-glass account (always issued role=super_admin below, which is
    # the one role allowed to carry a null org_id claim) and is otherwise
    # only ever set from the admin's own Firestore record.
    user_org_id = None

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
            # org_id=None here (a location_admin/coach record with no
            # assigned org) is not given the super_admin exception — their
            # token will simply fail closed at token_required on every
            # subsequent request, same as if the claim were absent entirely.
            user_org_id = admin.get('org_id')
    except Exception as e:
        logger.error(f"Firestore auth lookup failed: {e}")
        # Fail closed — don't fall through to env-var credentials on Firestore errors
        return jsonify({'error': 'Authentication service unavailable'}), 503

    # Fallback to environment-variable credentials (only if explicitly configured)
    if not authenticated and ADMIN_USERNAME and ADMIN_PASSWORD and username == ADMIN_USERNAME and _hmac.compare_digest(ADMIN_PASSWORD, password):
        authenticated = True
        user_role = VALID_ROLES[0]  # 'super_admin' — the break-glass account gets the top role
        # user_org_id stays None: there's no admin_users record for this
        # account, and None is exactly what the super_admin cross-org
        # exception expects.

    if authenticated:
        token = jwt.encode({
            'username': display_name,
            'role': user_role,
            'org_id': user_org_id,
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
    """Refresh JWT token, preserving the user's current role and org_id."""
    token = jwt.encode({
        'username': current_user,
        # No default role string: token_required already denies entry here
        # if the original token had no role, so this should never fire — but
        # if it somehow does, the refreshed token must inherit that same
        # denial rather than upgrading to a working role.
        'role': getattr(g, 'current_user_role', None),
        # Must carry org_id forward too: token_required set this from the
        # token being refreshed, and omitting it here would mint a token
        # with no 'org_id' claim at all -- which token_required's fail-closed
        # check would then reject on the very next request for anyone but
        # super_admin.
        'org_id': getattr(g, 'current_user_org_id', None),
        'exp': datetime.now(timezone.utc) + timedelta(hours=Config.JWT_EXPIRY_HOURS)
    }, Config.SECRET_KEY, algorithm="HS256")

    return jsonify({
        'token': token,
        'expires_in': Config.JWT_EXPIRY_HOURS * 3600
    }), 200
