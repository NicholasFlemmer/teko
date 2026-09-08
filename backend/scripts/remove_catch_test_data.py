"""One-off production cleanup: remove the CATCH Trust test/QA data found by
the read-only audit of production Firestore (project teko-236ad). See chat
history for the audit's full findings; the exact document IDs below are
copied from that audit's output, not re-derived by any query in this file.

Scope: CATCH Trust org 2I8r2Hb2q7pNgjDbcG8w only. Every document this script
touches is re-fetched immediately before being touched and its own org_id is
checked against the resolved CATCH org_id first -- a document that doesn't
belong to CATCH Trust (wrong org_id, or already gone) is refused and that
one action is aborted, never silently skipped past. The one deliberate,
narrow exception to this is check_in_tokens with org_id=None -- see C below
and _resolve_check_in_token_ownership's docstring.

Planned actions (see TARGETS below for the literal IDs) -- decisions as of
the second review:
  A. Unwind, then delete coaches/YEWnHpxXLI2nHslutDeP ("ZZZ TEST - DELETE ME
     (Ricki safeguarding test)"):
       - remove its id from coach_ids on teams/0AdhRXO7eqDqYanSI2fx and
         teams/3QW6hD9oDfqhdVpImOHu (read-modify-write on coach_ids, same
         convention as every other list field in this codebase -- no
         ArrayRemove/ArrayUnion is used anywhere here)
       - DELETE sessions/nBKzunqxv6CC9MElCZge outright (decision made: this
         session only ever had this one test coach on it). Its team_id and
         team name are printed so it's clear whose missed-practice count
         drops by one.
       - delete safeguarding_flags/Yi8DMLbZEhHAgKDETSsK
       - delete the coach doc
  B. Delete coaches/mOGHG43eBkRluQBSHsV9 ("Test Coach") -- no references
     found by the audit; this script re-checks that at run time before
     deleting (see _check_coach_unreferenced... actually just _get_scoped,
     the audit's "no references" claim is not re-verified by a fresh
     reference scan here, only org_id/existence is).
  C. coaches/wkIBkvjIkPVYa4IInqaB ("Test Coach", same email/phone as B):
       - delete the three check_in_tokens pointing at it, under the
         explicit ownership-by-linkage exception approved for this cleanup:
         a token with org_id=None is treated as CATCH-owned only if BOTH
         its coach_id resolves to a coach doc with org_id==CATCH AND its
         session_id resolves to a session doc with org_id==CATCH. A token
         whose org_id is present and NOT CATCH is still refused exactly as
         before -- this exception only ever loosens the org_id=None case.
       - sessions/LKFOIshpwdpyNwu7wAyb: remove ONLY 'wkIBkvjIkPVYa4IInqaB'
         from coach_ids (FirebaseService.update_session with a coach_ids-
         only payload -- no other field is touched). Whether that coach id
         also appears in coach_check_ins on this session is reported; if it
         does, that entry is printed and deliberately left in place.
       - delete the coach doc
  D. Delete three unreferenced locations: 34LWZV6spL7uGoO6C7HQ,
     6rjkwsXPoNfO7RHVWNbP, fEy6yyYtenGYcld94yNd.
  E. admin_users/AYMFjDkI6bx9zBvrrz7C ("Coach"/"Test", role=coach): printed
     in full (password value never printed), then DISABLED -- status=
     'disabled', is_active=False -- same fields, same reasoning, as
     disable_demo_accounts.py. Never deleted.
     admin_users/xHNAVHsDP0kw1QqJIG4g (ricki.badge.test, role=super_admin)
     is REMOVED FROM THE PLAN ENTIRELY per explicit decision -- this script
     never reads or writes it. Not in ADMINS_TO_DISABLE, not in TARGETS.
  F. coaches/v6ZMHUQfsiaGixNlJOmU (Siviuwe) is a real coach with no phone
     number on file, not test data. It is not in TARGETS and this script
     never reads or writes it.

Safety (double guard from create_catch_trust_location_admins.py /
disable_demo_accounts.py, 20s probe + strict org_id abort from
stamp_orphaned_content_url.py):
  - Dry run by default. Nothing is written unless you pass --commit.
  - Refuses to run against any project except teko-236ad, checked twice:
    the configured FIREBASE_PROJECT_ID (before Firebase init), and the
    project the SDK actually connected to (after Firebase init).
  - 20s hard-timeout connectivity probe before any read, so an expired ADC
    token fails fast instead of hanging.
  - org_id for CATCH Trust is resolved live from the organisations
    collection, cross-checked against KNOWN_ORG_ID, and aborts (does not
    fall back) on any mismatch or ambiguity.
  - Every target is looked up by its exact, hardcoded ID from TARGETS --
    no collection-wide query decides what gets touched. Each lookup's own
    org_id is re-checked against the resolved CATCH org_id before it is
    added to the plan; a mismatch refuses that action and continues with
    the rest (never aborts the whole run over one already-gone/reassigned
    document). The one narrow, explicit exception is check_in_tokens with
    org_id=None -- see C above.
  - In --commit mode, before the FIRST write, every document this run will
    change or delete is dumped in full to a JSON file OUTSIDE the repo at
    /private/tmp/teko_catch_test_data_backup_<timestamp>.json. If that file
    cannot be written, the script aborts before making any write.
  - admin_users/AYMFjDkI6bx9zBvrrz7C is DISABLED (status/is_active), never
    deleted -- matches disable_demo_accounts.py so any historical record
    it's attached to stays intact.

Usage:
    cd backend
    python -m scripts.remove_catch_test_data            # dry run
    python -m scripts.remove_catch_test_data --commit   # actually write
"""
import argparse
import concurrent.futures
import datetime as _dt
import json
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import firebase_admin
from services.firebase_service import FirebaseService
from config import Config

TARGET_PROJECT_ID = "teko-236ad"
PROBE_TIMEOUT_S = 20

ORG_NAME = "CATCH Trust"
KNOWN_ORG_ID = "2I8r2Hb2q7pNgjDbcG8w"  # cross-check only, not trusted blindly

BACKUP_PATH_TEMPLATE = "/private/tmp/teko_catch_test_data_backup_{ts}.json"

# ---------------------------------------------------------------------------
# Literal targets from the read-only audit. Nothing here is derived from a
# collection-wide query -- every ID is copied verbatim from that audit.
# ---------------------------------------------------------------------------

TARGETS = {
    "coach_a": {"id": "YEWnHpxXLI2nHslutDeP", "label": "ZZZ TEST - DELETE ME (Ricki safeguarding test)"},
    "coach_b": {"id": "mOGHG43eBkRluQBSHsV9", "label": "Test Coach (orphaned)"},
    "coach_c": {"id": "wkIBkvjIkPVYa4IInqaB", "label": "Test Coach (referenced)"},
    "coach_siviuwe": {"id": "v6ZMHUQfsiaGixNlJOmU", "label": "Siviuwe (real coach -- never touched)"},
}

TEAMS_TO_UNWIND_COACH_A = ["0AdhRXO7eqDqYanSI2fx", "3QW6hD9oDfqhdVpImOHu"]
SESSION_TO_DELETE_A = "nBKzunqxv6CC9MElCZge"       # coach_a -- decision: delete whole doc
SESSION_TO_UNWIND_COACH_C = "LKFOIshpwdpyNwu7wAyb"  # coach_c -- decision: remove from coach_ids only

SAFEGUARDING_FLAG_TO_DELETE = "Yi8DMLbZEhHAgKDETSsK"  # tied to coach_a

CHECK_IN_TOKENS_TO_DELETE = [
    "635fae97-1b1b-45cd-ba64-78498c0667e9",
    "76206864-321a-4eda-85c1-0132535de58d",
    "ad973bdc-fb96-462d-815e-25dee7e54f6b",
]  # all coach_id == coach_c; org_id=None on all three per the audit

LOCATIONS_TO_DELETE = [
    {"id": "34LWZV6spL7uGoO6C7HQ", "label": "sirroco test"},
    {"id": "6rjkwsXPoNfO7RHVWNbP", "label": "QA test delete me"},
    {"id": "fEy6yyYtenGYcld94yNd", "label": "Sea Point Test"},
]

# admin_users/xHNAVHsDP0kw1QqJIG4g (ricki.badge.test) is deliberately NOT
# listed here -- removed from the plan entirely per explicit decision. This
# script never reads or writes it.
ADMINS_TO_DISABLE = [
    {"id": "AYMFjDkI6bx9zBvrrz7C", "label": "last_name Test"},
]

_LAST_LOGIN_FIELD_CANDIDATES = ("last_login", "last_login_at", "last_active", "last_active_at", "last_signed_in_at")


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


def _resolve_org_id(db):
    exact = list(db.collection("organisations").where("name", "==", ORG_NAME).limit(2).stream())
    candidates = exact
    if len(candidates) != 1:
        candidates = [
            doc for doc in db.collection("organisations").stream()
            if ORG_NAME.lower() in str((doc.to_dict() or {}).get("name", "")).lower()
        ]
    if len(candidates) != 1:
        print(f"ERROR: could not uniquely resolve org_id for {ORG_NAME!r}.")
        if not candidates:
            print("  No organisation matched by exact name or case-insensitive substring.")
        else:
            print("  Multiple candidates found:")
            for doc in candidates:
                print(f"    id={doc.id}  name={(doc.to_dict() or {}).get('name')!r}")
        sys.exit(1)

    doc = candidates[0]
    org_id = doc.id
    stored_name = (doc.to_dict() or {}).get("name")
    print(f"Resolved org_id for {ORG_NAME!r}: {org_id}  (stored name: {stored_name!r})")
    if org_id != KNOWN_ORG_ID:
        print(
            f"ERROR: refusing to run -- resolved org_id {org_id!r} does not match the "
            f"known value {KNOWN_ORG_ID!r}. Aborting rather than acting on an unexpected org_id."
        )
        sys.exit(1)
    print(f"  Matches known org_id {KNOWN_ORG_ID!r}.\n")
    return org_id


def _json_default(value):
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    return str(value)


def _redact_password(data):
    """Copy of a doc's fields with any password-shaped field blanked --
    used only for the backup dump and for printing, never for the actual
    write payload."""
    redacted = dict(data)
    for key in list(redacted.keys()):
        if "password" in key.lower():
            redacted[key] = "<redacted>"
    return redacted


def _get_scoped(db, collection, doc_id, org_id, label):
    """Fetch a document by exact ID and refuse it if it doesn't exist or
    belongs to a different org_id. Returns the dict (with 'id') or None --
    None means "skip this action", already printed why."""
    doc = db.collection(collection).document(doc_id).get()
    if not doc.exists:
        print(f"  REFUSED: {collection}/{doc_id} ({label}) does not exist. Skipping this action.")
        return None
    data = {"id": doc.id, **(doc.to_dict() or {})}
    if data.get("org_id") != org_id:
        print(
            f"  REFUSED: {collection}/{doc_id} ({label}) has org_id={data.get('org_id')!r}, "
            f"expected {org_id!r}. Refusing to touch a document outside CATCH Trust. Skipping this action."
        )
        return None
    return data


def _resolve_check_in_token_ownership(db, token_id, org_id, expected_coach_id):
    """check_in_tokens-only exception, approved explicitly for this cleanup:
    a token whose org_id field is None is treated as belonging to CATCH
    Trust if AND ONLY IF both (a) its coach_id resolves to a coach doc with
    org_id==CATCH, and (b) its session_id resolves to a session doc with
    org_id==CATCH. A token whose org_id is present and NOT CATCH is still
    refused exactly like every other collection -- this exception only ever
    loosens the org_id=None case, never a genuine mismatch. Applies to
    check_in_tokens only; every other collection keeps the plain _get_scoped
    org_id check.
    """
    doc = db.collection("check_in_tokens").document(token_id).get()
    if not doc.exists:
        print(f"  REFUSED: check_in_tokens/{token_id} does not exist. Skipping.")
        return None
    data = {"id": doc.id, **(doc.to_dict() or {})}
    stored_org_id = data.get("org_id")

    if stored_org_id is not None:
        if stored_org_id != org_id:
            print(
                f"  REFUSED: check_in_tokens/{token_id} has org_id={stored_org_id!r}, "
                f"expected {org_id!r}. Skipping."
            )
            return None
        return data  # org_id present and matches -- no exception needed.

    # org_id is None -- apply the explicit ownership-by-linkage exception.
    if data.get("coach_id") != expected_coach_id:
        print(
            f"  REFUSED: check_in_tokens/{token_id} has org_id=None and coach_id="
            f"{data.get('coach_id')!r} != expected {expected_coach_id!r}. Skipping."
        )
        return None

    coach_doc = _get_scoped(db, "coaches", expected_coach_id, org_id, "coach for token ownership check")
    if not coach_doc:
        print(f"  REFUSED: check_in_tokens/{token_id} -- coach_id does not resolve to a CATCH coach. Skipping.")
        return None

    session_id = data.get("session_id")
    session_doc = _get_scoped(db, "sessions", session_id, org_id, "session for token ownership check") if session_id else None
    if not session_doc:
        print(f"  REFUSED: check_in_tokens/{token_id} -- session_id={session_id!r} does not resolve to a CATCH session. Skipping.")
        return None

    print(
        f"  OWNERSHIP CONFIRMED (org_id=None exception): check_in_tokens/{token_id} "
        f"coach_id={expected_coach_id} resolves to a CATCH coach, session_id={session_id} resolves to a CATCH session."
    )
    return data


def _print_admin_full(admin, label):
    print(f"  --- FULL ADMIN DUMP: admin_users/{admin['id']} ({label}) ---")
    print(f"    username:    {admin.get('username')}")
    print(f"    email:       {admin.get('email')}")
    print(f"    first_name:  {admin.get('first_name')}")
    print(f"    last_name:   {admin.get('last_name')}")
    print(f"    role:        {admin.get('role')}")
    print(f"    org_id:      {admin.get('org_id')}")
    print(f"    status:      {admin.get('status')}")
    print(f"    is_active:   {admin.get('is_active')}")
    print(f"    created_at:  {admin.get('created_at')}")
    found_last_login = False
    for field in _LAST_LOGIN_FIELD_CANDIDATES:
        if field in admin:
            print(f"    {field}:  {admin.get(field)}")
            found_last_login = True
    if not found_last_login:
        print(f"    (no last-login field present -- checked: {', '.join(_LAST_LOGIN_FIELD_CANDIDATES)})")
    for key in sorted(admin.keys()):
        if key in {"id", "username", "email", "first_name", "last_name", "role", "org_id",
                    "status", "is_active", "created_at", *_LAST_LOGIN_FIELD_CANDIDATES}:
            continue
        if "password" in key.lower():
            print(f"    {key}:  <redacted>")
        else:
            print(f"    {key}:  {admin.get(key)}")
    print()


def _write_backup(backup_docs):
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = BACKUP_PATH_TEMPLATE.format(ts=ts)
    try:
        with open(path, "w") as f:
            json.dump(backup_docs, f, indent=2, default=_json_default)
    except OSError as e:
        print(f"ERROR: could not write backup file at {path}: {e}")
        print("Refusing to proceed with any write until a backup can be written.")
        sys.exit(1)
    print(f"Backup of every document this run will change or delete written to: {path}\n")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually write to Firestore. Without this flag, only prints the plan.",
    )
    args = parser.parse_args()

    # --- Guard 1: configured project, before Firebase init -----------------
    configured_project = getattr(Config, "FIREBASE_PROJECT_ID", None)
    print(f"Configured FIREBASE_PROJECT_ID: {configured_project!r}")
    if configured_project != TARGET_PROJECT_ID:
        print(f"ERROR: refusing to run -- expected {TARGET_PROJECT_ID!r}, got {configured_project!r}.")
        sys.exit(1)

    if not args.commit:
        print("DRY RUN -- no writes will be made. Re-run with --commit to actually write.\n")

    FirebaseService.initialize()
    db = FirebaseService.get_db()
    if db is None:
        print("ERROR: Could not connect to Firestore. Run `gcloud auth application-default login` and try again.")
        sys.exit(1)

    # --- Guard 2: actual connected project, after Firebase init ------------
    actual_project = firebase_admin.get_app().project_id
    if actual_project != TARGET_PROJECT_ID:
        print(f"ERROR: refusing to run -- Firebase app initialized against {actual_project!r}, not {TARGET_PROJECT_ID!r}.")
        sys.exit(1)
    print(f"Confirmed connected project: {actual_project!r}\n")

    # --- 20s connectivity probe, hard-timeout guarded -----------------------
    print(f"Probing connectivity (org list, timeout {PROBE_TIMEOUT_S}s)...")

    def _probe():
        return list(db.collection("organisations").select([]).stream())

    _run_with_timeout(_probe, PROBE_TIMEOUT_S, "organisations probe")
    print("Probe OK.\n")

    org_id = _resolve_org_id(db)

    backup_docs = []  # list of {"collection": ..., "id": ..., "data": {...}} -- every doc this run will change/delete
    plan = []  # list of (description, fn_to_execute_if_commit, kind) -- kind in {"delete", "update"}

    print("=" * 100)
    print("PLAN")
    print("=" * 100)

    # ---- A. coaches/YEWnHpxXLI2nHslutDeP ------------------------------------
    print(f"\n--- A. Unwind + delete coaches/{TARGETS['coach_a']['id']} ({TARGETS['coach_a']['label']}) ---")
    coach_a = _get_scoped(db, "coaches", TARGETS["coach_a"]["id"], org_id, TARGETS["coach_a"]["label"])
    if coach_a:
        backup_docs.append({"collection": "coaches", "id": coach_a["id"], "data": coach_a})
        for team_id in TEAMS_TO_UNWIND_COACH_A:
            team = _get_scoped(db, "teams", team_id, org_id, "team referencing coach_a")
            if not team:
                continue
            current_coach_ids = list(team.get("coach_ids") or [])
            if coach_a["id"] not in current_coach_ids:
                print(f"  NOTE: teams/{team_id} coach_ids does not currently contain {coach_a['id']} -- nothing to remove.")
                continue
            new_coach_ids = [c for c in current_coach_ids if c != coach_a["id"]]
            backup_docs.append({"collection": "teams", "id": team["id"], "data": team})
            print(f"  Would update teams/{team_id}: coach_ids {current_coach_ids!r} -> {new_coach_ids!r}")

            def _do_unwind_team(team_id=team_id, new_coach_ids=new_coach_ids):
                FirebaseService.update_team(team_id, {"coach_ids": new_coach_ids})

            plan.append((f"teams/{team_id}.coach_ids remove {coach_a['id']}", _do_unwind_team, "update"))

        session_a = _get_scoped(db, "sessions", SESSION_TO_DELETE_A, org_id, "session referencing coach_a")
        if session_a:
            team_id_a = session_a.get("team_id")
            team_for_session_a = _get_scoped(db, "teams", team_id_a, org_id, "team for session_a") if team_id_a else None
            team_name_a = (team_for_session_a or {}).get("name")
            print(f"  --- sessions/{session_a['id']} -- DECISION: DELETE WHOLE DOCUMENT ---")
            print(f"    team_id:   {team_id_a}")
            print(f"    team name: {team_name_a!r}")
            print(f"    date: {session_a.get('date')}  status: {session_a.get('status')}")
            print(f"    Deleting this session drops team {team_name_a!r} ({team_id_a})'s missed-practice count by one.")
            backup_docs.append({"collection": "sessions", "id": session_a["id"], "data": session_a})
            print(f"  Would delete sessions/{session_a['id']}")

            def _do_delete_session_a(session_id=session_a["id"]):
                FirebaseService.delete_session(session_id)

            plan.append((f"delete sessions/{session_a['id']}", _do_delete_session_a, "delete"))

        flag = _get_scoped(db, "safeguarding_flags", SAFEGUARDING_FLAG_TO_DELETE, org_id, "flag tied to coach_a")
        if flag:
            backup_docs.append({"collection": "safeguarding_flags", "id": flag["id"], "data": flag})
            print(f"  Would delete safeguarding_flags/{flag['id']}")

            def _do_delete_flag(flag_id=flag["id"]):
                db.collection("safeguarding_flags").document(flag_id).delete()

            plan.append((f"delete safeguarding_flags/{flag['id']}", _do_delete_flag, "delete"))

        print(f"  Would delete coaches/{coach_a['id']}")

        def _do_delete_coach_a(coach_id=coach_a["id"]):
            FirebaseService.delete_coach(coach_id)

        plan.append((f"delete coaches/{coach_a['id']}", _do_delete_coach_a, "delete"))

    # ---- B. coaches/mOGHG43eBkRluQBSHsV9 ------------------------------------
    print(f"\n--- B. Delete coaches/{TARGETS['coach_b']['id']} ({TARGETS['coach_b']['label']}) -- no references ---")
    coach_b = _get_scoped(db, "coaches", TARGETS["coach_b"]["id"], org_id, TARGETS["coach_b"]["label"])
    if coach_b:
        backup_docs.append({"collection": "coaches", "id": coach_b["id"], "data": coach_b})
        print(f"  Would delete coaches/{coach_b['id']}")

        def _do_delete_coach_b(coach_id=coach_b["id"]):
            FirebaseService.delete_coach(coach_id)

        plan.append((f"delete coaches/{coach_b['id']}", _do_delete_coach_b, "delete"))

    # ---- C. coaches/wkIBkvjIkPVYa4IInqaB -------------------------------------
    print(f"\n--- C. coaches/{TARGETS['coach_c']['id']} ({TARGETS['coach_c']['label']}) ---")
    coach_c = _get_scoped(db, "coaches", TARGETS["coach_c"]["id"], org_id, TARGETS["coach_c"]["label"])
    if coach_c:
        backup_docs.append({"collection": "coaches", "id": coach_c["id"], "data": coach_c})

        for token_id in CHECK_IN_TOKENS_TO_DELETE:
            token = _resolve_check_in_token_ownership(db, token_id, org_id, coach_c["id"])
            if not token:
                continue
            backup_docs.append({"collection": "check_in_tokens", "id": token["id"], "data": token})
            print(f"  Would delete check_in_tokens/{token_id}")

            def _do_delete_token(token_id=token_id):
                db.collection("check_in_tokens").document(token_id).delete()

            plan.append((f"delete check_in_tokens/{token_id}", _do_delete_token, "delete"))

        session_c = _get_scoped(db, "sessions", SESSION_TO_UNWIND_COACH_C, org_id, "session referencing coach_c")
        if session_c:
            current_coach_ids = list(session_c.get("coach_ids") or [])
            target_id = coach_c["id"]
            if target_id not in current_coach_ids:
                print(f"  NOTE: sessions/{session_c['id']} coach_ids does not currently contain {target_id} -- nothing to remove.")
            else:
                new_coach_ids = [c for c in current_coach_ids if c != target_id]
                coach_check_ins = session_c.get("coach_check_ins") or {}
                if target_id in coach_check_ins:
                    print(f"  REPORT: {target_id} DOES appear in coach_check_ins on sessions/{session_c['id']}:")
                    print(f"    {coach_check_ins[target_id]!r}")
                    print(f"    Leaving this coach_check_ins entry in place -- only coach_ids is being updated.")
                else:
                    print(f"  REPORT: {target_id} does NOT appear in coach_check_ins on sessions/{session_c['id']}.")

                backup_docs.append({"collection": "sessions", "id": session_c["id"], "data": session_c})
                print(
                    f"  Would update sessions/{session_c['id']}: coach_ids {current_coach_ids!r} -> "
                    f"{new_coach_ids!r}  (no other field touched)"
                )

                def _do_unwind_session_c(session_id=session_c["id"], new_coach_ids=new_coach_ids):
                    FirebaseService.update_session(session_id, {"coach_ids": new_coach_ids})

                plan.append((f"sessions/{session_c['id']}.coach_ids remove {target_id}", _do_unwind_session_c, "update"))

        print(f"  Would delete coaches/{coach_c['id']}")

        def _do_delete_coach_c(coach_id=coach_c["id"]):
            FirebaseService.delete_coach(coach_id)

        plan.append((f"delete coaches/{coach_c['id']}", _do_delete_coach_c, "delete"))

    # ---- D. Locations ---------------------------------------------------------
    print("\n--- D. Delete three unreferenced locations ---")
    for loc in LOCATIONS_TO_DELETE:
        location = _get_scoped(db, "locations", loc["id"], org_id, loc["label"])
        if location:
            backup_docs.append({"collection": "locations", "id": location["id"], "data": location})
            print(f"  Would delete locations/{loc['id']} ({loc['label']!r})")

            def _do_delete_location(location_id=loc["id"]):
                FirebaseService.delete_location(location_id)

            plan.append((f"delete locations/{loc['id']}", _do_delete_location, "delete"))

    # ---- E. Admin: disable, do not delete. xHNAVHsDP0kw1QqJIG4g removed -----
    # from the plan entirely per explicit decision -- not read, not touched.
    print("\n--- E. Disable admin_users/AYMFjDkI6bx9zBvrrz7C (status='disabled', is_active=False) -- never deleted ---")
    print("      admin_users/xHNAVHsDP0kw1QqJIG4g (ricki.badge.test) REMOVED FROM PLAN -- not read, not touched.")
    for adm in ADMINS_TO_DISABLE:
        admin = _get_scoped(db, "admin_users", adm["id"], org_id, adm["label"])
        if admin:
            backup_docs.append({"collection": "admin_users", "id": admin["id"], "data": _redact_password(admin)})
            _print_admin_full(admin, adm["label"])
            print(f"  Would set on admin_users/{admin['id']}: status='disabled', is_active=False")

            def _do_disable_admin(admin_id=admin["id"]):
                db.collection("admin_users").document(admin_id).update({"status": "disabled", "is_active": False})

            plan.append((f"disable admin_users/{admin['id']}", _do_disable_admin, "update"))

    # ---- F. Siviuwe: never touched ---------------------------------------------
    print(f"\n--- F. coaches/{TARGETS['coach_siviuwe']['id']} (Siviuwe) -- real coach, NOT read or touched by this script ---")

    delete_count = sum(1 for _, _, kind in plan if kind == "delete")
    update_count = sum(1 for _, _, kind in plan if kind == "update")

    print("\n" + "=" * 100)
    print(f"PLAN SUMMARY: {len(plan)} write(s) planned -- {delete_count} delete(s), {update_count} field update(s).")
    print("=" * 100)
    for desc, _, kind in plan:
        print(f"  - [{kind}] {desc}")

    if not args.commit:
        print("\nDry run only -- nothing written. Re-run with --commit to apply this exact plan.")
        return

    # --- Backup, before the first write --------------------------------------
    print(f"\n{len(backup_docs)} document(s) will be backed up before any write.")
    _write_backup(backup_docs)

    print("Executing plan...")
    for desc, fn, kind in plan:
        fn()
        print(f"  DONE [{kind}]: {desc}")

    print("\nDone.")


if __name__ == "__main__":
    main()
