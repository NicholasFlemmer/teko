"""Session-wide safety guard: this test suite must never run against a
production Firestore project.

pytest always imports a directory's conftest.py before collecting any test
module inside it, so the check below runs before a single test file in
tests/ is even imported -- not just before any test executes. This replaces
the same staging-pre-load block that used to be duplicated at the top of
every test file (see git history on this repo for the removed copies): that
per-file approach meant whichever file pytest happened to import FIRST
decided FIREBASE_PROJECT_ID for the entire session, since config.py reads it
into a class attribute exactly once, at first import, and never re-reads it.
This file removes that race entirely by being the one and only place the
decision gets made, before anything else in tests/ can run.

Fails closed in every direction:
  - No backend/.env.staging on disk -> abort. An absent staging file is
    read as "not configured for tests", never as permission to fall
    through to backend/.env (the client's production project).
  - FIREBASE_PROJECT_ID already set in the environment to anything other
    than the expected staging project, BEFORE this file even loads
    .env.staging -> abort immediately. This is checked first, deliberately,
    so a value someone exported in their shell can't ride along underneath
    the override=True load below and silently get treated as fine.
  - FIREBASE_PROJECT_ID still not the expected staging project AFTER
    loading .env.staging (e.g. the file itself was edited to point
    somewhere else, or doesn't define the key at all) -> abort.

There is no skip, no warning, no fallback. Any of the above raises
immediately at collection time, which fails the whole pytest session before
it starts -- not a single test in tests/ can run until this passes.
"""
import os

from dotenv import load_dotenv

# The one and only Firestore project this suite is ever allowed to touch.
# Hardcoded here (not read back out of .env.staging) so a mis-edited
# .env.staging can't quietly move the goalposts -- this file is the
# independent source of truth for what counts as "safe", not a mirror of
# whatever the staging file happens to say today.
_EXPECTED_STAGING_PROJECT_ID = 'teko-staging-tgh'

_STAGING_ENV_PATH = os.path.join(os.path.dirname(__file__), '..', '.env.staging')


def _abort(message):
    raise RuntimeError(f"SAFETY ABORT (backend/tests/conftest.py): {message}")


def _enforce_staging_firestore_project():
    # Checked before the override=True load below on purpose: if someone
    # has already exported FIREBASE_PROJECT_ID=teko-236ad (or anything else)
    # in their shell, that must abort the run rather than being silently
    # clobbered back to the staging value by the load that follows.
    pre_existing = os.environ.get('FIREBASE_PROJECT_ID')
    if pre_existing is not None and pre_existing != _EXPECTED_STAGING_PROJECT_ID:
        _abort(
            f"FIREBASE_PROJECT_ID={pre_existing!r} is already set in the "
            f"environment, and it is not the staging project "
            f"({_EXPECTED_STAGING_PROJECT_ID!r}). Refusing to run this test "
            f"suite against any other Firestore project -- including the "
            f"client's production database (teko-236ad). Unset "
            f"FIREBASE_PROJECT_ID (or set it to the staging project) before "
            f"running tests."
        )

    if not os.path.exists(_STAGING_ENV_PATH):
        _abort(
            f"{_STAGING_ENV_PATH} not found. This suite must never fall "
            f"through to backend/.env (FIREBASE_PROJECT_ID=teko-236ad, the "
            f"client's production database) -- an absent staging file "
            f"aborts the run rather than being treated as permission to use "
            f"production. Create backend/.env.staging before running tests."
        )

    load_dotenv(dotenv_path=_STAGING_ENV_PATH, override=True)
    os.environ['FIREBASE_CREDENTIALS_PATH'] = ''  # force ADC, never a service account key

    project_id = os.environ.get('FIREBASE_PROJECT_ID')
    if project_id != _EXPECTED_STAGING_PROJECT_ID:
        _abort(
            f"after loading {_STAGING_ENV_PATH}, FIREBASE_PROJECT_ID resolved "
            f"to {project_id!r}, expected {_EXPECTED_STAGING_PROJECT_ID!r}. "
            f"Refusing to run this test suite against any other Firestore "
            f"project -- including the client's production database "
            f"(teko-236ad)."
        )


_enforce_staging_firestore_project()
