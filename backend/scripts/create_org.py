"""Create a new organisation ("tenant") and its first admin user.

A supported, repeatable path for onboarding a new tenant, as opposed to
migrate_add_orgs.py (a one-time migration for the very first org) or
seed_staging_test_data.py (throwaway test fixtures). Generic: no org name
or org_id is hardcoded anywhere in this file.

Reuses:
  - The idempotent-by-slug lookup from migrate_add_orgs.py's
    get_or_create_org() (match the `organisations` collection by `slug`,
    never create a duplicate) -- via FirebaseService.get_organisation_by_slug(),
    which is the same lookup that function performs by hand. This script is
    stricter than migrate_add_orgs.py: an existing slug is reported and
    changes NOTHING, whereas migrate_add_orgs.py backfills a field onto its
    single reused org. That backfill behaviour is deliberately not carried
    over here.
  - The "one admin_users record per org" shape from
    seed_staging_test_data.py's _seed_org() (name, email, role, org_id,
    status='active', password hashed with werkzeug's pbkdf2:sha256 --
    see its comment on why pbkdf2 and not werkzeug's scrypt default).
    Generalised here to take name/email/role as CLI arguments instead of
    seed_staging_test_data.py's hardcoded per-test-org values, and to
    generate a real random password (there is no fixed test password to
    reuse for a real tenant's admin).
  - The double project guard, ADC connectivity timeout probe, and
    --commit/dry-run-by-default pattern shared by
    stamp_orphaned_content_url.py, create_catch_trust_location_admins.py
    and disable_demo_accounts.py.

Does NOT reuse migrate_add_orgs.py's org_id backfill across collections --
that is a migration for pre-existing documents and is out of scope for a
brand-new tenant, which by definition has none.

Every organisation field is an explicit, required CLI argument (see --help)
-- there is no default that could silently omit a field. safeguarding_lead_email
is additionally validated as a real, non-placeholder address: an org can be
created without ever having named a safeguarding lead, but not with a
placeholder standing in for one. The first admin_users record (name, email,
role) is likewise required -- an org with no admin can never be
administered.

Idempotent by slug: if an organisation with the given slug already exists,
it is reported and nothing is written -- not the org, not the admin.

Usage:
    cd backend
    python -m scripts.create_org \\
        --name "Acme FC" --slug acme-fc --type sports \\
        --timezone Africa/Johannesburg --country "South Africa" \\
        --supported-languages English Afrikaans \\
        --works-with-minors true --attendance-mode named \\
        --safeguarding-lead-name "Jane Doe" \\
        --safeguarding-lead-email jane@acmefc.org \\
        --admin-name "Jane Doe" --admin-email jane@acmefc.org \\
        --admin-role location_admin
                                                        # dry run (default)
    ... --commit                                       # actually write
"""
import argparse
import concurrent.futures
import re
import secrets as _secrets
import string
import sys
import os
import zoneinfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import firebase_admin
from werkzeug.security import generate_password_hash
from services.firebase_service import FirebaseService
from routes.auth import VALID_ROLES
from config import Config

TARGET_PROJECT_ID = "teko-236ad"
PROBE_TIMEOUT_S = 20

# Mirrors routes/organisations.py's own (module-private) _VALID_ATTENDANCE_MODES
# and _EMAIL_RE -- duplicated rather than imported since those are named
# private to that module, not part of its public surface.
_VALID_ATTENDANCE_MODES = {'named', 'headcount'}
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

# Domains/local-parts that are syntactically valid emails but obviously not a
# real safeguarding contact. ".invalid" mirrors seed_staging_test_data.py's
# own use of that reserved TLD for "obviously fake, can never resolve" test
# addresses -- the same reasoning applies here in reverse: real safeguarding
# leads must never be seeded with those in place of a real address.
_PLACEHOLDER_DOMAINS = {
    'example.com', 'example.org', 'example.net', 'example.invalid',
    'test.invalid', 'localhost',
}
_PLACEHOLDER_DOMAIN_SUFFIXES = ('.invalid', '.example', '.test')
_PLACEHOLDER_LOCAL_PARTS = {
    'placeholder', 'todo', 'tbd', 'changeme', 'none', 'n/a', 'na', 'xxx',
}

PASSWORD_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"


class OrgCreationError(Exception):
    """Raised for any validation failure or safety refusal. Never raised
    part-way through a Firestore write -- every check in create_org() runs
    before the first write, so this always means nothing was written."""


def _generate_password(length=20):
    """Cryptographically secure password with guaranteed character diversity."""
    while True:
        pw = "".join(_secrets.choice(PASSWORD_ALPHABET) for _ in range(length))
        if (
            any(c.islower() for c in pw)
            and any(c.isupper() for c in pw)
            and any(c.isdigit() for c in pw)
            and any(c in "!@#$%^&*()-_=+" for c in pw)
        ):
            return pw


def _is_placeholder_email(email):
    local, _, domain = email.partition('@')
    domain = domain.lower()
    if domain in _PLACEHOLDER_DOMAINS or domain.endswith(_PLACEHOLDER_DOMAIN_SUFFIXES):
        return True
    if local.lower() in _PLACEHOLDER_LOCAL_PARTS:
        return True
    return False


def _validate_safeguarding_email(raw):
    """safeguarding_lead_email is mandatory: refuse on empty, malformed, or
    an obvious placeholder standing in for a real safeguarding contact."""
    email = (raw or "").strip()
    if not email:
        raise OrgCreationError(
            "safeguarding_lead_email is mandatory -- refusing to create the "
            "org without it."
        )
    if not _EMAIL_RE.match(email):
        raise OrgCreationError(f"safeguarding_lead_email {email!r} is not a valid email address.")
    if _is_placeholder_email(email):
        raise OrgCreationError(
            f"safeguarding_lead_email {email!r} looks like a placeholder, not a "
            f"real safeguarding contact. Refusing to create the org."
        )
    return email


def _validate_admin(name, email, role):
    """An org with no admin can never be administered -- refuse without one."""
    name = (name or "").strip()
    email = (email or "").strip()
    role = (role or "").strip()
    if not name or not email or not role:
        raise OrgCreationError(
            "An admin (name, email, role) is required -- an org with no "
            "admin can never be administered. Refusing to create the org."
        )
    if not _EMAIL_RE.match(email):
        raise OrgCreationError(f"admin email {email!r} is not a valid email address.")
    if role not in VALID_ROLES:
        raise OrgCreationError(
            f"admin role must be one of: {', '.join(VALID_ROLES)} (got {role!r})."
        )
    return name, email.lower(), role


def _validate_choice(label, value, choices):
    if value not in choices:
        raise OrgCreationError(f"{label} must be one of: {', '.join(sorted(choices))} (got {value!r}).")


def _validate_timezone(tz):
    if tz not in zoneinfo.available_timezones():
        raise OrgCreationError(f"timezone {tz!r} is not a valid IANA timezone name.")


def _mask_email(email):
    local, _, domain = email.partition('@')
    if not domain:
        return '***'
    masked_local = '*' * len(local) if len(local) <= 2 else local[0] + '*' * (len(local) - 2) + local[-1]
    return f"{masked_local}@{domain}"


def create_org(args, commit=False):
    """Validate everything, check idempotency, then (if commit) write the
    organisation and its first admin. Pure aside from the two
    FirebaseService calls -- no argparse, no project guard, no ADC probe --
    so it can be exercised directly with FirebaseService monkeypatched,
    independent of main()'s production-project guard.

    Returns a result dict:
      {'status': 'exists', 'org_id': ..., 'org_name': ...}
      {'status': 'dry_run', 'org_fields': {...}, 'admin_name': ..., 'admin_email': ..., 'admin_role': ...}
      {'status': 'created', 'org_id': ..., 'admin_id': ..., 'admin_email': ..., 'admin_password': ...}

    Raises OrgCreationError, before any write, on any validation failure.
    """
    safeguarding_email = _validate_safeguarding_email(args.safeguarding_lead_email)
    admin_name, admin_email, admin_role = _validate_admin(args.admin_name, args.admin_email, args.admin_role)
    _validate_choice('type', args.type, FirebaseService.DEFAULT_TERMINOLOGY_BY_TYPE.keys())
    _validate_choice('attendance_mode', args.attendance_mode, _VALID_ATTENDANCE_MODES)
    _validate_timezone(args.timezone)

    slug = args.slug.strip()
    if not slug:
        raise OrgCreationError("slug is required.")

    existing = FirebaseService.get_organisation_by_slug(slug)
    if existing:
        return {
            'status': 'exists',
            'org_id': existing['id'],
            'org_name': existing.get('name'),
        }

    # Every org field the org takes, and nothing else -- see module
    # docstring. created_at is added by FirebaseService.create_organisation.
    org_fields = {
        'name': args.name,
        'slug': slug,
        'type': args.type,
        'timezone': args.timezone,
        'country': args.country,
        'supported_languages': list(args.supported_languages),
        'works_with_minors': args.works_with_minors,
        'attendance_mode': args.attendance_mode,
        'safeguarding_lead_name': args.safeguarding_lead_name,
        'safeguarding_lead_email': safeguarding_email,
        'is_active': True,
    }

    if not commit:
        return {
            'status': 'dry_run',
            'org_fields': org_fields,
            'admin_name': admin_name,
            'admin_email': admin_email,
            'admin_role': admin_role,
        }

    org = FirebaseService.create_organisation(dict(org_fields))

    password = _generate_password()
    admin_fields = {
        'name': admin_name,
        'email': admin_email,
        'password': generate_password_hash(password, method='pbkdf2:sha256'),
        'role': admin_role,
        'org_id': org['id'],
        # status, not is_active: this is the field auth.py's login() actually
        # gates on (admin.get('status', 'active')) -- see disable_demo_accounts.py.
        'status': 'active',
        'is_active': True,
    }
    admin = FirebaseService.create_admin(admin_fields)

    return {
        'status': 'created',
        'org_id': org['id'],
        'admin_id': admin['id'],
        'admin_email': admin_email,
        'admin_password': password,
    }


def _print_result(result):
    status = result['status']
    if status == 'exists':
        print(
            f"Organisation with this slug already exists (id: {result['org_id']}, "
            f"name: {result['org_name']!r}) -- reporting and changing nothing."
        )
        return

    if status == 'dry_run':
        print("Would create organisation:")
        for key in sorted(result['org_fields']):
            print(f"    {key}: {result['org_fields'][key]!r}")
        print("    created_at: <server timestamp, set on write>")
        print("Would create admin_users record:")
        print(f"    name: {result['admin_name']!r}")
        print(f"    email: {_mask_email(result['admin_email'])!r}")
        print(f"    role: {result['admin_role']!r}")
        print("    status: 'active'")
        print("    is_active: True")
        print("    password: <generated at write time, not shown in dry run>")
        print("    created_at: <server timestamp, set on write>")
        print("\nDry run only -- nothing written. Re-run with --commit to apply.")
        return

    if status == 'created':
        print(f"Created organisation (id: {result['org_id']}).")
        print(f"Created admin_users record (id: {result['admin_id']}).")
        print(f"  Admin login email: {_mask_email(result['admin_email'])}")
        print(f"  Admin password (shown once, not stored anywhere else): {result['admin_password']}")


def _run_with_timeout(fn, timeout_s, label):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn)
        try:
            return future.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            print(
                f"ERROR: {label} did not respond within {timeout_s}s -- treating this as "
                f"an expired/hung ADC token, not a slow query. Run "
                f"`gcloud auth application-default login` and try again."
            )
            sys.exit(1)


def _build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--name', required=True, help="Organisation display name.")
    parser.add_argument('--slug', required=True, help="Unique slug -- also the idempotency key.")
    parser.add_argument('--type', required=True, choices=sorted(FirebaseService.DEFAULT_TERMINOLOGY_BY_TYPE.keys()),
                         help="Organisation type; drives default terminology.")
    parser.add_argument('--timezone', required=True, help="IANA timezone, e.g. Africa/Johannesburg.")
    parser.add_argument('--country', required=True, help="Country name.")
    parser.add_argument('--supported-languages', required=True, nargs='+', metavar='LANGUAGE',
                         help="One or more supported languages.")
    parser.add_argument('--works-with-minors', required=True, type=_parse_bool, metavar='true|false',
                         help="Whether this org works with minors.")
    parser.add_argument('--attendance-mode', required=True, choices=sorted(_VALID_ATTENDANCE_MODES),
                         help="'named' (per-player register) or 'headcount'.")
    parser.add_argument('--safeguarding-lead-name', required=True, help="Name of the safeguarding lead.")
    parser.add_argument('--safeguarding-lead-email', required=True,
                         help="Email of the safeguarding lead. Mandatory -- no placeholder accepted.")
    parser.add_argument('--admin-name', required=True, help="Name of the first admin user for this org.")
    parser.add_argument('--admin-email', required=True, help="Email of the first admin user.")
    parser.add_argument('--admin-role', required=True, choices=sorted(VALID_ROLES),
                         help="Role for the first admin user.")
    parser.add_argument('--commit', action='store_true',
                         help="Actually write to Firestore. Without this flag, only prints what would be written.")
    return parser


def _parse_bool(value):
    v = value.strip().lower()
    if v in ('true', 'yes', '1'):
        return True
    if v in ('false', 'no', '0'):
        return False
    raise argparse.ArgumentTypeError(f"expected true/false, got {value!r}")


def main():
    args = _build_parser().parse_args()

    configured_project = getattr(Config, "FIREBASE_PROJECT_ID", None)
    print(f"Configured FIREBASE_PROJECT_ID: {configured_project!r}")
    if configured_project != TARGET_PROJECT_ID:
        print(f"ERROR: refusing to run — expected {TARGET_PROJECT_ID!r}, got {configured_project!r}.")
        sys.exit(1)

    if not args.commit:
        print("DRY RUN — no writes will be made. Re-run with --commit to actually create the org.\n")

    FirebaseService.initialize()
    db = FirebaseService.get_db()
    if db is None:
        print("ERROR: Could not connect to Firestore. Run `gcloud auth application-default login` and try again.")
        sys.exit(1)

    actual_project = firebase_admin.get_app().project_id
    if actual_project != TARGET_PROJECT_ID:
        print(f"ERROR: refusing to run — Firebase app initialized against {actual_project!r}, not {TARGET_PROJECT_ID!r}.")
        sys.exit(1)
    print(f"Confirmed connected project: {actual_project!r}\n")

    print(f"Probing connectivity (org list, timeout {PROBE_TIMEOUT_S}s)...")

    def _probe():
        return list(db.collection("organisations").select([]).stream())

    _run_with_timeout(_probe, PROBE_TIMEOUT_S, "organisations probe")
    print("Probe OK.\n")

    try:
        result = create_org(args, commit=args.commit)
    except OrgCreationError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    _print_result(result)


if __name__ == '__main__':
    main()
