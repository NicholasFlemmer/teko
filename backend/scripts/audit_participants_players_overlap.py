"""Throwaway, READ-ONLY production audit script.

Purpose: compare the `players` and `participants` Firestore collections
(org scoping, volume, field population, age profile, overlap) and confirm
whether PersonService.resolve() can currently match a phone number to a
`players` record. This informs a safeguarding escalation design; it does
not implement one.

This script performs ONLY reads against production Firestore (teko-236ad).
It contains no .set(), .update(), .delete(), .add(), or batch/transaction
write calls anywhere. It is intentionally NOT committed to git.

Usage:
    cd backend
    FIREBASE_PROJECT_ID=teko-236ad python3 scripts/audit_participants_players_overlap.py
"""
import os
import re
import sys
from collections import Counter
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import firebase_admin  # noqa: E402
from firebase_admin import credentials, firestore  # noqa: E402

EXPECTED_PROJECT_ID = 'teko-236ad'

read_count = 0


def normalize_phone(raw):
    """Basic normalisation for overlap comparison only: strip everything
    but digits, then drop a leading country/trunk prefix down to the last
    9 digits so e.g. '+27821234567', '0821234567', '27821234567' compare
    equal. Read-only helper, does not touch stored data."""
    if not raw or not isinstance(raw, str):
        return None
    digits = re.sub(r'\D', '', raw)
    if not digits:
        return None
    return digits[-9:] if len(digits) >= 9 else digits


def normalize_name(raw):
    if not raw or not isinstance(raw, str):
        return None
    return ' '.join(raw.strip().lower().split())


def try_parse_dob(raw):
    """Try a handful of common stored formats. Returns a date or None."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.strip()
    fmts = ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d', '%d-%m-%Y']
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def fetch_all(db, collection_name):
    global read_count
    docs = list(db.collection(collection_name).stream())
    read_count += len(docs)
    records = []
    for d in docs:
        data = d.to_dict() or {}
        data['_doc_id'] = d.id
        records.append(data)
    return records


def section(title):
    print()
    print('=' * 80)
    print(title)
    print('=' * 80)


def is_present_nonempty(v):
    if v is None:
        return False
    if isinstance(v, str) and v.strip() == '':
        return False
    return True


def main():
    project_id = os.environ.get('FIREBASE_PROJECT_ID')
    print(f"FIREBASE_PROJECT_ID in use: {project_id!r}")
    if project_id != EXPECTED_PROJECT_ID:
        print(f"ABORTING: FIREBASE_PROJECT_ID must be exactly {EXPECTED_PROJECT_ID!r}, "
              f"got {project_id!r}.")
        sys.exit(1)

    try:
        if not firebase_admin._apps:
            cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred, {'projectId': project_id})
        db = firestore.client()
    except Exception as e:
        print(f"ABORTING: Firebase/ADC initialization failed: {e!r}")
        sys.exit(1)

    print(f"Connected. firestore client project: {db.project}")
    if db.project != EXPECTED_PROJECT_ID:
        print(f"ABORTING: firestore client is bound to project {db.project!r}, "
              f"expected {EXPECTED_PROJECT_ID!r}.")
        sys.exit(1)

    try:
        players = fetch_all(db, 'players')
        participants = fetch_all(db, 'participants')
    except Exception as e:
        print(f"ABORTING: read against Firestore failed: {e!r}")
        sys.exit(1)

    # ---------------------------------------------------------------
    section('A. ORG SCOPING')
    for label, records in (('players', players), ('participants', participants)):
        total = len(records)
        with_org = sum(1 for r in records if is_present_nonempty(r.get('org_id')))
        without_org = total - with_org
        print(f"\n[{label}] total={total} with_org_id={with_org} without_org_id={without_org}")
        org_counts = Counter(r.get('org_id') if is_present_nonempty(r.get('org_id')) else '(missing)'
                              for r in records)
        print(f"[{label}] distinct org_id values and counts:")
        for org_id, count in sorted(org_counts.items(), key=lambda kv: (-kv[1], str(kv[0]))):
            print(f"    {org_id!r}: {count}")

    # ---------------------------------------------------------------
    section('B. VOLUME')
    print(f"\nTotal players: {len(players)}")
    print(f"Total participants: {len(participants)}")
    for label, records in (('players', players), ('participants', participants)):
        org_counts = Counter(r.get('org_id') if is_present_nonempty(r.get('org_id')) else '(missing)'
                              for r in records)
        print(f"\n[{label}] per org_id:")
        for org_id, count in sorted(org_counts.items(), key=lambda kv: (-kv[1], str(kv[0]))):
            print(f"    {org_id!r}: {count}")

    # ---------------------------------------------------------------
    section('C. FIELD POPULATION ON PLAYERS')
    total_players = len(players)
    fields_to_check = [
        'date_of_birth', 'guardian_name', 'guardian_email',
        'guardian_primary_phone', 'guardian_secondary_phone',
        'phone_number', 'phone', 'contact_number',
    ]
    print(f"\n(total players = {total_players})")
    for field in fields_to_check:
        present = sum(1 for r in players if is_present_nonempty(r.get(field)))
        missing = total_players - present
        pct_present = (present / total_players * 100) if total_players else 0.0
        pct_missing = (missing / total_players * 100) if total_players else 0.0
        print(f"  {field:24s} present={present:5d} ({pct_present:5.1f}%)   "
              f"missing/empty={missing:5d} ({pct_missing:5.1f}%)")

    # ---------------------------------------------------------------
    section('D. AGE PROFILE')
    today = date.today()
    parsed_count = 0
    unparseable = []
    under_18 = 0
    over_18 = 0
    for r in players:
        raw_dob = r.get('date_of_birth')
        if not is_present_nonempty(raw_dob) and not isinstance(raw_dob, (datetime, date)):
            continue
        parsed = try_parse_dob(raw_dob)
        if parsed is None:
            unparseable.append(raw_dob)
            continue
        parsed_count += 1
        age = today.year - parsed.year - ((today.month, today.day) < (parsed.month, parsed.day))
        if age < 18:
            under_18 += 1
        else:
            over_18 += 1

    print(f"\nPlayers with a usable (parseable) date_of_birth: {parsed_count}")
    print(f"  Under 18 as of {today.isoformat()}: {under_18}")
    print(f"  18 or over as of {today.isoformat()}: {over_18}")
    print(f"Dates of birth present but unparseable: {len(unparseable)}")
    print("Example raw unparseable values (up to 3):")
    for v in unparseable[:3]:
        print(f"    {v!r}")

    # ---------------------------------------------------------------
    section('E. OVERLAP')

    participant_phones = {}
    for r in participants:
        norm = normalize_phone(r.get('phone_number'))
        if norm:
            participant_phones.setdefault(norm, []).append(r.get('_doc_id'))

    player_phone_fields = ['phone_number', 'phone', 'contact_number',
                            'guardian_primary_phone', 'guardian_secondary_phone']
    player_phones = {}
    for r in players:
        for field in player_phone_fields:
            norm = normalize_phone(r.get(field))
            if norm:
                player_phones.setdefault(norm, []).append((r.get('_doc_id'), field))

    phone_matches = set(participant_phones.keys()) & set(player_phones.keys())
    print(f"\nExact phone-number matches (normalised, digits-only, last 9 digits) "
          f"between participants and players: {len(phone_matches)}")
    for norm in list(phone_matches)[:10]:
        print(f"    {norm}: participant doc_ids={participant_phones[norm]}  "
              f"player (doc_id, field)={player_phones[norm]}")
    if len(phone_matches) > 10:
        print(f"    ... and {len(phone_matches) - 10} more")

    participant_names = {}
    for r in participants:
        norm = normalize_name(r.get('name'))
        if norm:
            participant_names.setdefault(norm, []).append(r.get('_doc_id'))

    player_names = {}
    for r in players:
        name_val = r.get('name') or (
            f"{r.get('first_name', '')} {r.get('last_name', '')}".strip()
            if (r.get('first_name') or r.get('last_name')) else None
        )
        norm = normalize_name(name_val)
        if norm:
            player_names.setdefault(norm, []).append(r.get('_doc_id'))

    name_matches = set(participant_names.keys()) & set(player_names.keys())
    print(f"\nExact name matches (case-insensitive, trimmed) between participants "
          f"and players: {len(name_matches)}")
    for norm in list(name_matches)[:10]:
        print(f"    {norm!r}: participant doc_ids={participant_names[norm]}  "
              f"player doc_ids={player_names[norm]}")
    if len(name_matches) > 10:
        print(f"    ... and {len(name_matches) - 10} more")

    cross_ref_field_names = ['player_id', 'participant_id']
    player_fields_seen = set()
    for r in players:
        player_fields_seen.update(r.keys())
    participant_fields_seen = set()
    for r in participants:
        participant_fields_seen.update(r.keys())

    print("\nCross-reference field check (player_id / participant_id):")
    any_cross_ref = False
    for f in cross_ref_field_names:
        in_players = f in player_fields_seen
        in_participants = f in participant_fields_seen
        if in_players or in_participants:
            any_cross_ref = True
        print(f"    {f!r}: present on players={in_players}, present on participants={in_participants}")
    print(f"  ANY existing cross-reference field found: {'YES' if any_cross_ref else 'NO'}")

    # ---------------------------------------------------------------
    section('F. IDENTITY RESOLUTION')
    print("""
PersonService.resolve() (backend/services/person_service.py) builds exactly
two in-memory caches: _coach_cache (from FirebaseService.get_all_coaches,
line 90) and _participant_cache (from FirebaseService.get_all_participants,
line 91). resolve() (lines 123-185) only ever looks up the normalised phone
against _coach_cache (line 166) and _participant_cache (line 167) — the
`players` collection is never queried or cached anywhere in this file.

ANSWER: NO. PersonService.resolve() cannot currently match an incoming
phone number to a `players` record. A phone number that exists only on a
players/guardian document (and not on a coaches or participants document)
resolves to None (no match) — see person_service.py lines 154-185, and the
cache-population code at lines 89-108 which never references
FirebaseService.get_all_players or the 'players' collection at all.

File: backend/services/person_service.py
  - resolve():                        lines 123-185
  - phone lookups against caches:     lines 166-167
  - cache population (coaches/participants only, no players): lines 89-108
""")

    # ---------------------------------------------------------------
    section('G. SCHEMA DUMP')
    print(f"\nDistinct field names observed across all {len(players)} players documents:")
    for f in sorted(player_fields_seen):
        print(f"    {f}")
    print(f"\nDistinct field names observed across all {len(participants)} participants documents:")
    for f in sorted(participant_fields_seen):
        print(f"    {f}")

    # ---------------------------------------------------------------
    section('SAFETY CONFIRMATION')
    print(f"\nTotal Firestore document reads performed: {read_count}")
    print("Write/delete/update/add/batch/transaction calls made by this script: 0")
    print("This script contains no .set(), .update(), .delete(), .add(), "
          "batch(), or transaction() calls.")


if __name__ == '__main__':
    main()
