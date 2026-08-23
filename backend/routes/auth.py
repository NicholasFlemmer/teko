from flask import Blueprint, request, jsonify, g
import hmac as _hmac
import jwt
import logging
import os
from datetime import datetime, timedelta, timezone
from config import Config
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash
from services.rate_limiter import is_rate_limited
from utils.request_ip import get_trusted_client_ip
from services.auth_token_service import (
    create_auth_token,
    consume_auth_token,
    TokenNotFound,
    TokenExpired,
    TokenAlreadyUsed,
    TokenTypeMismatch,
)
from services.email_service import send_password_reset_email, send_invite_email, send_welcome_email

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

# forgot-password sends real email and is a spam/enumeration target, so
# tighter than login on both axes, over a longer window matching the
# token's own lifetime: RESET_TOKEN_EXPIRY_MINUTES below is 60, so
# there's rarely a legitimate reason to need more than a couple of
# requests inside that same hour. Per-email: 3/hour covers "the first
# email didn't arrive, try once more" without leaving room for using
# this endpoint to hammer one real inbox. Per-IP: 10/hour, looser for
# the same shared-office-network reason as login, still capping how many
# different emails one source can probe per hour.
FORGOT_PASSWORD_EMAIL_RATE_LIMIT = (3, 60 * 60)
FORGOT_PASSWORD_IP_RATE_LIMIT = (10, 60 * 60)

# reset-password has no email in its payload to rate-limit by (only a
# token + new password) -- IP only, as specified. 10/15min: generous
# enough for a legitimate retry (wrong password length, fat-fingered
# paste of the token), tight enough to blunt automated abuse. Brute-
# forcing the 256-bit token itself is already infeasible regardless of
# this limit; this is about the endpoint, not the token space.
RESET_PASSWORD_IP_RATE_LIMIT = (10, 15 * 60)

# Matches what the password-reset email template already claims
# ("This link expires in 1 hour" -- services/email_service.py).
RESET_TOKEN_EXPIRY_MINUTES = 60

# Canonical admin role vocabulary — matches the values already stored in
# Firestore admin_users. Import this rather than hardcoding role strings.
VALID_ROLES = ('super_admin', 'location_admin', 'coach')

# invite is authenticated (only super_admin/location_admin can call it),
# not a public enumeration target the way login/forgot-password are --
# but it still emails a real address on every successful call, so it's
# rate limited on both axes for the same reason those are: an inviter
# key (not the invitee's email, which is different on every call) stops
# a compromised admin token from email-bombing an unbounded list of
# addresses; an IP key stops the same abuse if the token itself somehow
# leaks. Inviter: 20/hour comfortably covers onboarding a whole team in
# one sitting. IP: looser (30/hour), same shared-office-network
# reasoning as login()/forgot_password() above.
INVITE_INVITER_RATE_LIMIT = (20, 60 * 60)
INVITE_IP_RATE_LIMIT = (30, 60 * 60)

# Matches what the invite email template already claims ("This link
# expires in 48 hours." -- services/email_service.py send_invite_email).
INVITE_TOKEN_EXPIRY_MINUTES = 48 * 60

# accept-invite has no email in its payload to rate-limit by (token +
# names + password only) -- IP only, identical reasoning to
# RESET_PASSWORD_IP_RATE_LIMIT: generous enough for a legitimate retry,
# tight enough to blunt automated abuse against the one endpoint in this
# file where an anonymous request creates a user.
ACCEPT_INVITE_IP_RATE_LIMIT = (10, 15 * 60)

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

    # get_admin_by_email does an exact string match with no normalisation
    # of its own (mirrors forgot_password() below) -- a capitalised or
    # whitespace-padded email must still match the stored record. Only used
    # for the Firestore lookup and its rate-limit key; the raw `username` is
    # kept as-is for the ADMIN_USERNAME break-glass comparison below, which
    # is a literal secret match, not an email lookup.
    normalized_username = username.strip().lower()

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
    email_rate_limited = is_rate_limited(f"login:email:{normalized_username}", *LOGIN_EMAIL_RATE_LIMIT)
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
        admin = FirebaseService.get_admin_by_email(normalized_username, include_password=True)
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


@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    """Request a password reset link.

    The main security property: this MUST NOT reveal whether `email`
    belongs to a real account. Every normal-path outcome below returns
    the exact same `generic_response` object -- built once, before any
    branch that depends on account existence, so it's provably the same
    bytes regardless of which path is taken. A 429 (rate limited) or 503
    (email service unconfigured) are a different axis, not an
    email-existence leak -- both are checked, and fire identically,
    before any account-specific lookup happens at all.

    One asymmetry is accepted rather than eliminated: the outbound
    Resend network call only happens for a real, found account, so
    response TIMING differs between found and not-found by roughly that
    call's latency. Closing that gap would mean sending a real "reset
    your password" email to an address this endpoint has no reason to
    believe is an admin account -- turning it into a vector for
    harassing arbitrary strangers' inboxes, which is a worse trade than
    the timing side-channel it would close. This is the "as far as
    reasonably achievable" boundary, not an oversight.
    """
    data = request.get_json()
    if not data or not data.get('email'):
        return jsonify({'error': 'Email is required'}), 400

    # get_admin_by_email does an exact string match, no normalisation of
    # its own -- normalise here or a mixed-case/padded submission would
    # silently never match the stored record.
    email = data['email'].strip().lower()

    client_ip = get_trusted_client_ip(request.headers, remote_addr=request.remote_addr, allow_remote_addr_fallback=Config.DEBUG)
    email_rate_limited = is_rate_limited(f"forgot_password:email:{email}", *FORGOT_PASSWORD_EMAIL_RATE_LIMIT)
    ip_rate_limited = is_rate_limited(f"forgot_password:ip:{client_ip}", *FORGOT_PASSWORD_IP_RATE_LIMIT)
    if email_rate_limited or ip_rate_limited:
        return jsonify({'error': 'Too many requests. Please try again later.'}), 429

    # RESEND_API_KEY unconfigured is a deployment-wide state, not tied to
    # any specific email -- checked here, before any account lookup, so
    # this fires identically for every request regardless of whether
    # `email` is real. Relying on send_password_reset_email()'s own
    # raised EmailNotConfiguredError further down instead would only
    # ever surface on the found-branch (only a real account reaches the
    # send call), which would leak existence for as long as the
    # misconfiguration lasts -- this avoids that by failing the same way
    # for everyone, up front, rather than telling anyone to check an
    # inbox that was never going to receive anything.
    if not Config.RESEND_API_KEY:
        logger.error("[forgot-password] RESEND_API_KEY not configured — cannot send any reset email.")
        return jsonify({'error': 'Password reset is temporarily unavailable. Please try again later.'}), 503

    generic_response = (
        jsonify({'message': 'If an account exists for that email address, a password reset link has been sent.'}),
        200,
    )

    try:
        from services.firebase_service import FirebaseService
        admin = FirebaseService.get_admin_by_email(email)
    except Exception:
        logger.exception("[forgot-password] Firestore admin lookup failed.")
        # Fail closed on the lookup like login() does, but still the
        # generic response -- a Firestore error here can't vary by
        # email either, so returning anything else would only add a
        # third distinguishable outcome for no reason.
        return generic_response

    if admin:
        try:
            reset_token = create_auth_token('password_reset', admin['id'], RESET_TOKEN_EXPIRY_MINUTES)
            reset_link = f"{Config.FRONTEND_URL}/reset-password?token={reset_token}"
            name = admin.get('name') or admin.get('first_name') or 'there'
            send_password_reset_email(email, reset_link, name)
        except Exception as e:
            # A failure here (Resend configured but this specific send
            # call errored -- the "unconfigured" case is already handled
            # above and never reaches this branch) only happens for a
            # real account, so returning anything other than the generic
            # response would leak that. Logged for ops to notice and
            # follow up with the affected admin directly; the user-facing
            # response stays identical to every other outcome on this
            # path. Deliberate tradeoff, see docstring.
            #
            # type(e).__name__ only, never logger.exception()/str(e): this
            # exception originates from an email-send call, and Resend's
            # own client can embed the request payload -- i.e. reset_link,
            # i.e. the raw token -- in its exception's message, exactly
            # the failure mode email_service.py's own _send() is already
            # hardened against. logger.exception() would attach that
            # message (and a traceback) to the log record regardless of
            # what this call site's own format string says.
            logger.error(
                "[forgot-password] send_password_reset_email failed for an existing account (%s).",
                type(e).__name__,
            )

    return generic_response


@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    """Consume a password reset token and set a new password.

    Does not invalidate any session already issued before the reset --
    and with the current setup, cannot. JWTs here are stateless: signed
    with one global Config.SECRET_KEY, verified in token_required() by
    signature and 'exp' alone, with no per-user claim (a token_version,
    an issued-at-vs-password-changed-at comparison, anything) that a
    reset could invalidate and no revocation list anywhere in this
    codebase. A token issued five minutes before a reset stays valid
    until its own natural expiry (Config.JWT_EXPIRY_HOURS, 24h default)
    regardless of what happens here. Stating this plainly rather than
    implying otherwise: shipping session invalidation would need the JWT
    scheme itself to change (e.g. a stored per-admin token_version
    claim, checked against admin_users on every request), which is out
    of scope for this endpoint.
    """
    data = request.get_json()
    if not data or not data.get('token') or not data.get('password'):
        return jsonify({'error': 'Token and password are required'}), 400

    token = data['token']
    password = data['password']

    # Matches what the SuperAdmin create/edit-user form already states
    # ("Minimum 8 characters") and what POST /api/admin/users enforces.
    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400

    client_ip = get_trusted_client_ip(request.headers, remote_addr=request.remote_addr, allow_remote_addr_fallback=Config.DEBUG)
    if is_rate_limited(f"reset_password:ip:{client_ip}", *RESET_PASSWORD_IP_RATE_LIMIT):
        return jsonify({'error': 'Too many attempts. Please try again later.'}), 429

    # 400, not 401, for every token-validation failure below. api.ts's
    # shared request() helper intercepts every 401 globally and discards
    # the response body before ResetPassword.tsx's own message-mapping
    # ever sees it (documented in LOGIN_BUGS_FOUND.md) -- a 401 here
    # would silently break this endpoint's error messages exactly the
    # same way it already breaks login()'s. ResetPassword.tsx matches on
    # `message.includes('expired') || message.includes('Invalid')`
    # (case-sensitive) for its friendly copy; matched below.
    try:
        record = consume_auth_token(token, expected_type='password_reset')
    except TokenExpired:
        return jsonify({'error': 'This reset link has expired.'}), 400
    except TokenAlreadyUsed:
        return jsonify({'error': 'Invalid or already used reset link.'}), 400
    except (TokenNotFound, TokenTypeMismatch):
        return jsonify({'error': 'Invalid reset link.'}), 400

    admin_id = record.get('subject')
    try:
        from services.firebase_service import FirebaseService
        new_hash = generate_password_hash(password, method='pbkdf2:sha256')
        FirebaseService.update_admin(admin_id, {'password': new_hash})
    except Exception:
        logger.exception("[reset-password] Failed to write new password for admin_id=%s", admin_id)
        return jsonify({'error': 'Could not reset your password. Please try again.'}), 503

    return jsonify({'message': 'Your password has been reset successfully.'}), 200


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


@auth_bp.route('/invite', methods=['POST'])
@token_required
@role_required('super_admin', 'location_admin')
def invite(current_user):
    """Invite a new admin/coach account by email.

    role_required above already keeps a coach token out entirely (403
    before this body runs). The one restriction enforced here on top of
    that: a location_admin may not invite a super_admin -- letting a
    single-org role mint the one role with unrestricted cross-org access
    would be a straightforward privilege escalation.

    org_id is never read from the request body. The invited account
    always inherits the *inviter's own* org_id (g.current_user_org_id,
    set by token_required from the inviter's own token). "A
    location_admin can only invite into their own org" is therefore not
    a check that could be bypassed -- there is no field in this payload
    that could name a different org at all.

    Whether `email` already has an account is treated the same way
    forgot_password() treats it above: never revealed. Every normal-path
    outcome returns the identical `generic_response`, built once, before
    the account lookup. Unlike forgot_password(), an unconfigured mailer
    or a failed send is also folded into that same generic response
    (not a distinct 503) -- send only ever happens on the "no existing
    account" branch here, so a distinct status code on that branch alone
    would itself be an existence oracle, which forgot_password()'s own
    up-front RESEND_API_KEY check deliberately avoids by checking before
    any branch split. There's no equivalent safe place to check it here.
    """
    data = request.get_json()
    if not data or not data.get('email') or not data.get('role'):
        return jsonify({'error': 'Email and role are required'}), 400

    # get_admin_by_email does an exact string match with no normalisation
    # of its own -- same reasoning as login()/forgot_password() above.
    email = data['email'].strip().lower()
    role = data['role']

    if role not in VALID_ROLES:
        return jsonify({'error': f'Role must be one of: {", ".join(VALID_ROLES)}'}), 400

    inviter_role = getattr(g, 'current_user_role', None)
    if inviter_role == 'location_admin' and role == 'super_admin':
        return jsonify({'error': 'You do not have permission to invite a super_admin'}), 403

    client_ip = get_trusted_client_ip(request.headers, remote_addr=request.remote_addr, allow_remote_addr_fallback=Config.DEBUG)
    inviter_rate_limited = is_rate_limited(f"invite:inviter:{current_user}", *INVITE_INVITER_RATE_LIMIT)
    ip_rate_limited = is_rate_limited(f"invite:ip:{client_ip}", *INVITE_IP_RATE_LIMIT)
    if inviter_rate_limited or ip_rate_limited:
        return jsonify({'error': 'Too many invites sent. Please try again later.'}), 429

    org_id = getattr(g, 'current_user_org_id', None)

    generic_response = (
        jsonify({'message': 'If that email does not already have an account, an invitation has been sent.'}),
        200,
    )

    try:
        from services.firebase_service import FirebaseService
        existing = FirebaseService.get_admin_by_email(email)
    except Exception:
        logger.exception("[invite] Firestore admin lookup failed.")
        # Fail the same way forgot_password() does on this same class of
        # error: the generic response, not a distinct code -- a Firestore
        # error here can't vary by email either.
        return generic_response

    if existing:
        return generic_response

    try:
        invite_token = create_auth_token('invite', email, INVITE_TOKEN_EXPIRY_MINUTES, extra_fields={'role': role, 'org_id': org_id})
        invite_link = f"{Config.FRONTEND_URL}/accept-invite?token={invite_token}"
        org = FirebaseService.get_organisation(org_id) if org_id else None
        org_name = (org or {}).get('name') or 'Teko'
        send_invite_email(email, invite_link, org_name, current_user, role)
    except Exception as e:
        # type(e).__name__ only, never str(e)/logger.exception() -- same
        # reasoning as forgot_password()'s send failure handling: the
        # exception can embed invite_link (i.e. the raw token) in its
        # message.
        logger.error("[invite] send_invite_email failed for a new invite (%s).", type(e).__name__)

    return generic_response


@auth_bp.route('/accept-invite', methods=['POST'])
def accept_invite():
    """Consume an invite token and create the invited admin account.

    Unauthenticated by design -- an invitee has no token yet. This is
    the only endpoint in this file where an anonymous request creates a
    user, so every value that determines WHAT gets created (email, role,
    org_id) comes from the stored, server-issued token record, never
    from the request body. A payload that includes 'role' or 'org_id' is
    simply ignored: there is no code path below that reads those keys
    off `data` at all.
    """
    data = request.get_json()
    if not data or not data.get('token') or not data.get('first_name') or not data.get('last_name') or not data.get('password'):
        return jsonify({'error': 'Token, first name, last name, and password are required'}), 400

    token = data['token']
    first_name = data['first_name'].strip()
    last_name = data['last_name'].strip()
    password = data['password']

    if not first_name or not last_name:
        return jsonify({'error': 'First name and last name are required'}), 400

    # Matches what create_admin_user (routes/admin.py) already enforces.
    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400

    client_ip = get_trusted_client_ip(request.headers, remote_addr=request.remote_addr, allow_remote_addr_fallback=Config.DEBUG)
    if is_rate_limited(f"accept_invite:ip:{client_ip}", *ACCEPT_INVITE_IP_RATE_LIMIT):
        return jsonify({'error': 'Too many attempts. Please try again later.'}), 429

    # 400, not 401, for every token-validation failure below -- same
    # reasoning as reset_password() above (api.ts's global 401
    # interceptor; LOGIN_BUGS_FOUND.md). AcceptInvite.tsx matches on
    # `message.includes('expired') || message.includes('Invalid') ||
    # message.includes('already')` (case-sensitive) for its friendly
    # copy; matched below.
    try:
        record = consume_auth_token(token, expected_type='invite')
    except TokenExpired:
        return jsonify({'error': 'This invite link has expired.'}), 400
    except TokenAlreadyUsed:
        return jsonify({'error': 'Invalid or already used invite link.'}), 400
    except (TokenNotFound, TokenTypeMismatch):
        return jsonify({'error': 'Invalid invite link.'}), 400

    email = record.get('subject')
    role = record.get('role')
    org_id = record.get('org_id')

    if role not in VALID_ROLES:
        # A token minted before role validation existed, or corrupted
        # some other way -- fail closed rather than create an account
        # with an unrecognised role.
        logger.error("[accept-invite] Consumed invite token has an invalid role %r; refusing to create the account.", role)
        return jsonify({'error': 'This invite is no longer valid. Please ask for a new one.'}), 400

    try:
        from services.firebase_service import FirebaseService
        existing = FirebaseService.get_admin_by_email(email)
    except Exception:
        logger.exception("[accept-invite] Firestore admin lookup failed for email=%s", email)
        return jsonify({'error': 'Could not create your account. Please try again.'}), 503

    if existing:
        # Race: an account for this email was created after the invite
        # was sent (a direct admin-creation call, or two invites accepted
        # concurrently). The token is already consumed either way --
        # this must not overwrite the account that now exists.
        return jsonify({'error': 'An account with this email already exists.'}), 409

    try:
        password_hash = generate_password_hash(password, method='pbkdf2:sha256')
        FirebaseService.create_admin({
            'email': email,
            'first_name': first_name,
            'last_name': last_name,
            'password': password_hash,
            'role': role,
            'org_id': org_id,
            'status': 'active',
            'is_active': True,
        })
    except Exception:
        logger.exception("[accept-invite] Failed to create admin account for email=%s", email)
        return jsonify({'error': 'Could not create your account. Please try again.'}), 503

    # Best-effort: the account already exists at this point regardless of
    # whether this send succeeds. Never roll back a successful signup
    # because the welcome email bounced.
    try:
        org = FirebaseService.get_organisation(org_id) if org_id else None
        org_name = (org or {}).get('name') or 'Teko'
        login_url = f"{Config.FRONTEND_URL}/login"
        send_welcome_email(email, first_name, org_name, login_url)
    except Exception as e:
        logger.error("[accept-invite] send_welcome_email failed after account creation (%s).", type(e).__name__)

    return jsonify({'message': 'Your account has been created. You can now sign in.'}), 200
