"""One-off production cleanup: remove the Sporting Chance QA test data found
by the read-only audit of production Firestore (project teko-236ad).

Scope, decided in chat after the audit (both coaches and all sessions on the
team are being removed -- this was explicitly confirmed, not assumed, since
one of the two coaches, "Tim Human" (timo.human@gmail.com), shares an email
with the org's real safeguarding lead / location_admin and has a session
completed as recently as 2026-09-14):

  - teams/v8DWWmwlkVusfZsQ3QhK ("QA Test Team") -- delete.
  - coaches/E2aSph9fhrRyzDRX1Y8i ("Tim Human") -- delete.
  - coaches/BlkZIcpndkgajIgajBBC ("Ricki QA") -- delete.
  - All 7 sessions on this team -- delete, including the one shared between
    both coaches (pCVYq06dvLJYEDITV4u8, "QA Photo Test"). Session names
    ("QA Photo Test", "QA Photo Test 2 - single coach", "QA Photo Test 3 -
    final clean test") confirm these are feature-test sessions, not real
    attendance data.
  - 3 check_in_tokens tied to Tim's coach id (all already used=False and
    long expired) -- delete as harmless housekeeping so nothing points at a
    deleted session/coach.
  - locations/BqYnA8CDEBdm1tpUQirf ("QA Test Venue") -- delete. Confirmed by
    audit to be referenced by nothing else in this org (only this one team
    pointed at it).

NOT touched by this script, deliberately:
  - admin_users/maxFGiGVoKUFDPO3vORd (timo.human@gmail.com, role=
    location_admin) -- Tim's real admin login is a completely separate
    collection/document from his QA coach record and is never read or
    written here.
  - organisations/2sE6bU0GEnm3PKpg9zBv itself -- not touched by this script.

Safety (same pattern as remove_catch_test_data.py):
  - Dry run by default. Nothing is written unless you pass --commit.
  - Refuses to run against any project except teko-236ad, checked twice.
  - 20s hard-timeout connectivity probe before any read.
  - org_id for Sporting Chance is resolved live from the organisations
    collection, cross-checked against KNOWN_ORG_ID, and aborts on mismatch.
  - Every target is looked up by its exact, hardcoded ID from TARGETS -- no
    collection-wide query decides what gets touched. Each lookup's own
    org_id is re-checked against the resolved org_id before it is added to
    the plan; a mismatch refuses that one action and continues with the
    rest.
  - In --commit mode, before the first write, every document this run will
    delete is dumped in full to a JSON file OUTSIDE the repo at
    /private/tmp/teko_sporting_chance_qa_backup_<timestamp>.json. If that
    file cannot be written, the script aborts before making any write.

Usage:
    cd backend
    python -m scripts.remove_sporting_chance_qa_test_data            # dry run
    python -m scripts.remove_sporting_chance_qa_test_data --commit   # actually write
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

ORG_NAME = "Sporting Chance"
KNOWN_ORG_ID = "2sE6bU0GEnm3PKpg9zBv"  # cross-check only, not trusted blindly

BACKUP_PATH_TEMPLATE = "/private/tmp/teko_sporting_chance_qa_backup_{ts}.json"

TEAM_ID = "v8DWWmwlkVusfZsQ3QhK"
TEAM_LABEL = "QA Test Team"

COACHES_TO_DELETE = [
    {"id": "E2aSph9fhrRyzDRX1Y8i", "label": "Tim Human"},
    {"id": "BlkZIcpndkgajIgajBBC", "label": "Ricki QA"},
]

SESSIONS_TO_DELETE = [
    "8yIH4OXcwoC9gl1NgOQ0", "TYSpUuLRlzTLPmymX1o6", "pCVYq06dvLJYEDITV4u8",
    "pwctB0Mnlw3AX0Jk5qh2", "x2TDZnd20L6TvGx8PGNg", "x31CMDSCcbhWh4q1xLOH",
    "xNr5nzlCa3xDXDlukV04",
]

CHECK_IN_TOKENS_TO_DELETE = [
    "2c9fd6e7-8366-4332-927e-9cfe85151f33",
    "8da672e0-b94c-4fb4-92e2-810e3bd57daf",
    "fbc147d9-dada-493f-9b40-1754a6454fc7",
]  # all coach_id == Tim's coach doc; all used=False, all long expired

LOCATION_ID = "BqYnA8CDEBdm1tpUQirf"
LOCATION_LABEL = "QA Test Venue"


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


def _get_scoped(db, collection, doc_id, org_id, label):
    doc = db.collection(collection).document(doc_id).get()
    if not doc.exists:
        print(f"  REFUSED: {collection}/{doc_id} ({label}) does not exist. Skipping this action.")
        return None
    data = {"id": doc.id, **(doc.to_dict() or {})}
    if data.get("org_id") != org_id:
        print(
            f"  REFUSED: {collection}/{doc_id} ({label}) has org_id={data.get('org_id')!r}, "
            f"expected {org_id!r}. Refusing to touch a document outside Sporting Chance. Skipping this action."
        )
        return None
    return data


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
    print(f"Backup of every document this run will delete written to: {path}\n")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually write to Firestore. Without this flag, only prints the plan.",
    )
    args = parser.parse_args()

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

    actual_project = firebase_admin.get_app().project_id
    if actual_project != TARGET_PROJECT_ID:
        print(f"ERROR: refusing to run -- Firebase app initialized against {actual_project!r}, not {TARGET_PROJECT_ID!r}.")
        sys.exit(1)
    print(f"Confirmed connected project: {actual_project!r}\n")

    print(f"Probing connectivity (org list, timeout {PROBE_TIMEOUT_S}s)...")

    def _probe():
        return list(db.collection("organisations").select([]).stream())

    _run_with_timeout(_probe, PROBE_TIMEOUT_S, "organisations probe")
    print("Probe OK.\n")

    org_id = _resolve_org_id(db)

    backup_docs = []
    plan = []

    print("=" * 100)
    print("PLAN")
    print("=" * 100)

    print(f"\n--- Team: teams/{TEAM_ID} ({TEAM_LABEL}) ---")
    team = _get_scoped(db, "teams", TEAM_ID, org_id, TEAM_LABEL)
    if team:
        backup_docs.append({"collection": "teams", "id": team["id"], "data": team})
        print(f"  {team}")
        print(f"  Would delete teams/{TEAM_ID}")

        def _do_delete_team(team_id=TEAM_ID):
            FirebaseService.delete_team(team_id)

        plan.append((f"delete teams/{TEAM_ID}", _do_delete_team, "delete"))

    print(f"\n--- Coaches ---")
    for c in COACHES_TO_DELETE:
        coach = _get_scoped(db, "coaches", c["id"], org_id, c["label"])
        if coach:
            backup_docs.append({"collection": "coaches", "id": coach["id"], "data": coach})
            print(f"  {coach}")
            print(f"  Would delete coaches/{c['id']} ({c['label']})")

            def _do_delete_coach(coach_id=c["id"]):
                FirebaseService.delete_coach(coach_id)

            plan.append((f"delete coaches/{c['id']} ({c['label']})", _do_delete_coach, "delete"))

    print(f"\n--- Sessions ---")
    for sid in SESSIONS_TO_DELETE:
        session = _get_scoped(db, "sessions", sid, org_id, "session on QA Test Team")
        if session:
            backup_docs.append({"collection": "sessions", "id": session["id"], "data": session})
            print(f"  session {sid}: name={session.get('name')!r} status={session.get('status')!r} date={session.get('date')!r} coach_ids={session.get('coach_ids')!r}")
            print(f"  Would delete sessions/{sid}")

            def _do_delete_session(session_id=sid):
                FirebaseService.delete_session(session_id)

            plan.append((f"delete sessions/{sid}", _do_delete_session, "delete"))

    print(f"\n--- check_in_tokens (stale, tied to Tim's coach doc / these sessions) ---")
    for token_id in CHECK_IN_TOKENS_TO_DELETE:
        doc = db.collection("check_in_tokens").document(token_id).get()
        if not doc.exists:
            print(f"  REFUSED: check_in_tokens/{token_id} does not exist. Skipping.")
            continue
        data = {"id": doc.id, **(doc.to_dict() or {})}
        if data.get("org_id") != org_id:
            print(f"  REFUSED: check_in_tokens/{token_id} has org_id={data.get('org_id')!r}, expected {org_id!r}. Skipping.")
            continue
        backup_docs.append({"collection": "check_in_tokens", "id": data["id"], "data": data})
        print(f"  {data}")
        print(f"  Would delete check_in_tokens/{token_id}")

        def _do_delete_token(token_id=token_id):
            db.collection("check_in_tokens").document(token_id).delete()

        plan.append((f"delete check_in_tokens/{token_id}", _do_delete_token, "delete"))

    print(f"\n--- Location: locations/{LOCATION_ID} ({LOCATION_LABEL}) ---")
    location = _get_scoped(db, "locations", LOCATION_ID, org_id, LOCATION_LABEL)
    if location:
        backup_docs.append({"collection": "locations", "id": location["id"], "data": location})
        print(f"  {location}")
        print(f"  Would delete locations/{LOCATION_ID}")

        def _do_delete_location(location_id=LOCATION_ID):
            FirebaseService.delete_location(location_id)

        plan.append((f"delete locations/{LOCATION_ID}", _do_delete_location, "delete"))

    print("\n--- NOT touched: admin_users/maxFGiGVoKUFDPO3vORd (Tim's real location_admin login) -- never read or written by this script. ---")

    delete_count = sum(1 for _, _, kind in plan if kind == "delete")

    print("\n" + "=" * 100)
    print(f"PLAN SUMMARY: {len(plan)} deletion(s) planned.")
    print("=" * 100)
    for desc, _, kind in plan:
        print(f"  - [{kind}] {desc}")

    if not args.commit:
        print("\nDry run only -- nothing written. Re-run with --commit to apply this exact plan.")
        return

    print(f"\n{len(backup_docs)} document(s) will be backed up before any write.")
    _write_backup(backup_docs)

    print("Executing plan...")
    for desc, fn, kind in plan:
        fn()
        print(f"  DONE [{kind}]: {desc}")

    print("\nDone.")


if __name__ == "__main__":
    main()
