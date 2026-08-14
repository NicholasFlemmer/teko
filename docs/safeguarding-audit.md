# Safeguarding Escalation — Existing-System Audit

**Read-only audit. No code was changed to produce this document.**
Branch: `phase2-participant-identity`. Framework note: the backend is Flask (not FastAPI) — Blueprints, `jsonify`, `g` request context.

Purpose: before designing a safeguarding escalation path (a participant's WhatsApp disclosure of harm should reach a real human, not end at the AI's reply), this documents exactly what already exists to build on, and what's genuinely missing.

---

## 1. Notification channels that already exist

### Email

Email sending exists and is used today. `backend/services/email_service.py`:

- Provider: **Resend** (`import resend`, `backend/services/email_service.py:8`).
- Config: `Config.RESEND_API_KEY` and `Config.RESEND_FROM_EMAIL`, read from env vars at `backend/config.py:47-48` (`RESEND_API_KEY`, default `''`; `RESEND_FROM_EMAIL`, default `noreply@tekohq.com`).
- Low-level sender: `_send(to_email, subject, html, fallback_detail=None)` at `backend/services/email_service.py:71-90`. This is the one function that actually calls `resend.Emails.send(...)` (line 82) — any new email type would call through this.
- Three templated senders built on `_send`: `send_invite_email` (`:93`), `send_password_reset_email` (`:112`), `send_welcome_email` (`:130`). All three are transactional, admin-account-lifecycle emails only — no participant-facing or safeguarding-adjacent email exists today.
- Callers: `backend/routes/auth.py:214` (password reset), `:322` (invite), `:388` (welcome). Nothing outside `routes/auth.py` sends email.
- **Reliability**: if `RESEND_API_KEY` is unset, `_send` logs a warning and returns — it does not send, and does not raise (`email_service.py:73-78`). If the Resend API call itself throws, the exception is caught and logged at `ERROR`, again without re-raising (`email_service.py:89-90`). **A caller of `_send` can never observe an email failure** — see Section 5.

Conclusion: email is a real, working, already-wired channel, provider-backed (not a stub), and its low-level `_send` function is reusable for a new message type. But every existing use of it is fire-and-forget with no failure surfacing.

### Outbound WhatsApp outside a conversation reply

Two independent send functions exist, both used outside of replying to an inbound message:

- `WhatsAppService.send_message(phone_number, message_text, check_in_url=None)` — `backend/services/whatsapp_service.py:12-86`. Generic text send via the Meta WhatsApp Cloud API (`Config.WHATSAPP_API_URL`/`WHATSAPP_PHONE_NUMBER_ID`/`WHATSAPP_API_KEY`, `backend/config.py:36-39`). Returns `{"success": bool, ...}`, never raises on a failed send — see `whatsapp_service.py:68-86`.
- `WhatsAppService.send_template_message(...)` — used for approved WhatsApp Business templates (referenced at `backend/routes/broadcasts.py:158-163`).

Non-reply invocations:

- **Broadcasts**: `POST /api/broadcasts` (`backend/routes/broadcasts.py:84-227`, function `send_broadcast`) loops recipients and calls `WhatsAppService.send_template_message` or `.send_message` per recipient (`broadcasts.py:158-168`). This is an admin-triggered, on-demand send, not scheduled.
- **Scheduler** (`backend/services/scheduler_service.py`, started in `backend/app.py:81-107` via `BackgroundScheduler` from `apscheduler`, three jobs registered every 1/5/30 minutes):
  - `SchedulerService.check_and_send_reminders` (`scheduler_service.py:24-150`) — calls `WhatsAppService.send_check_in_reminder` (`:108-114`), itself built on the same `send_message`/template path.
  - `SchedulerService.send_end_session_prompts` (`:153-227`) — calls `WhatsAppService.send_message` directly (`:202-205`).
  - `SchedulerService.mark_missed_sessions` (`:230-288`) — no send, status-only.
  - A shared-secret-authenticated HTTP trigger also exists at `POST /api/scheduler/run-reminders` (`backend/app.py:142-155`), for Cloud Scheduler or manual admin triggering.

**Reusability**: yes — `WhatsAppService.send_message` is a plain, stateless function taking a phone number and text. A safeguarding notification to an admin's WhatsApp number could call it directly with no new client code, provided the recipient has a WhatsApp number on record (see Section 2 — this is not guaranteed for admins).

### In-app alerts / notifications / SSE

There is **no notification bell, alert badge, toast-from-backend-event, or persisted notifications collection anywhere in this codebase.** Confirmed by direct inspection:

- The only "Bell" icon in the frontend is the **Reminders** nav-sidebar entry (`frontend/src/components/layout/AppSidebar.tsx:12,75`) — it is a page icon, not a notification indicator.
- The toast components under `frontend/src/components/ui/toast.tsx`, `toaster.tsx`, `sonner.tsx`, `use-toast.ts` are generic shadcn/ui toast primitives used for local form-submit feedback (e.g. "Saved successfully") — none are wired to a backend event stream or push channel.
- No `notifications` Firestore collection exists (grep across `backend/services` and `backend/routes` found none).

**The SSE live-activity feed is the only real-time surface in the app**, and it is ephemeral, in-memory, and coach-event-scoped:

- Backend: `backend/routes/sse.py`. `push_event(event_type, coach_name=None, preview=None, extra=None)` (`sse.py:19-42`) appends to a process-local Python list `_event_list`, capped at `_MAX_EVENTS = 200` with hard trimming (`sse.py:16, 39-42`) — **nothing is persisted to Firestore or any durable store; a server restart or a second app instance loses the buffer entirely**, and it is not org-scoped (any authenticated viewer sees every org's events — no `.where('org_id', ...)` filter exists in `_stream_generator`).
- Endpoint: `GET /api/sse/coach-activity` (`sse.py:78-102`), JWT-authenticated via query param (`?token=`) since `EventSource` can't send headers.
- Event types actually pushed, all from `backend/services/conversation_service.py`: `attendance` (`:1028`), `photo_uploaded` (`:1235`), `check_in` (`:1423`), `message_received` (`:1659`), `response_sent` (`:1714` on success, `:1717` on send failure — preview literally `"[send failed]"`).
- Frontend consumer: `frontend/src/components/schedule/LiveActivityFeed.tsx`, a `<EventSource>` hook rendering the last 50 events in a scrolling card on the Schedule page. It is a dashboard widget an admin must be actively looking at — there is no unread count, no persistence across page loads, no sound/desktop notification, and no participant-message events (only the coach path calls `push_event`; `_handle_participant_message`, `conversation_service.py:1761-1794`, never does).

**Conclusion for Section 1**: nobody would be reliably alerted by anything that exists today if a participant disclosed harm over WhatsApp. Email and WhatsApp-send are both real, reusable, already-in-production channels — but nothing currently routes a participant message into either of them, and the one real-time surface (SSE) is ephemeral, not participant-aware, and requires an admin to be looking at the dashboard at that exact moment.

---

## 2. Who would receive an escalation

### `admin_users` collection

Defined via `FirebaseService.create_admin` (`backend/services/firebase_service.py:872-881`, docstring: "Fields: name, email, password_hash, role, status, created_at") and constructed concretely at `backend/routes/admin.py:94-100`:

```python
user = FirebaseService.create_admin({
    'name': data['name'].strip(),
    'email': email,
    'password': generate_password_hash(data['password']),
    'role': data['role'],
    'org_id': org_id,
})
```

Fields actually present: `name`, `email`, `password` (hashed), `role`, `org_id`, `created_at` (server timestamp, `firebase_service.py:878`). **No `phone_number`/WhatsApp field on an admin user anywhere** — only `email` is contactable at the platform level, so any WhatsApp escalation to an admin is not currently possible without adding a field.

Roles: **inconsistent across the codebase.** `routes/admin.py:75` validates `allowed_roles = ['admin', 'superadmin', 'viewer']` on create, but `routes/auth.py:301-305` and `routes/organisations.py:20,140` check for `'super_admin'`, `'location_admin'`, `'coach'` (note the underscore and the different vocabulary — `super_admin` vs `superadmin`). This is a pre-existing inconsistency, not something introduced by this audit; it matters here because "who is a super_admin" is not a single, consistently-enforced concept.

`email` is a required, non-empty field on every admin user (`routes/admin.py:66-72`), so every admin record does have a contactable email address — that part is reliable.

### Organisation record

`FirebaseService.create_organisation` (`backend/services/firebase_service.py:1079-1094`, docstring: "Fields: name, slug, type, terminology, ai_persona_prompt, country, supported_languages, is_active, created_at") and the update whitelist at `backend/routes/organisations.py:79` (`allowed_fields = ['name', 'type', 'terminology', 'ai_persona_prompt', 'country', 'supported_languages']`).

**There is no `contact_person`, `contact_email`, `contact_phone`, or any equivalent field on the Organisation record.** Stated plainly: it does not exist.

### Designated safeguarding contact

**Nothing resembling a "safeguarding contact," "designated safeguarding lead," "DSL," or "escalation contact" exists anywhere in the codebase** — confirmed by direct inspection of `backend/routes/`, `backend/services/`, and the `participants`/`players` schemas. It does not exist. Do not assume any such concept is half-built somewhere.

However, one closely related and directly reusable precedent **does** exist, on a different collection: the legacy `players` collection (`backend/services/firebase_service.py:514-527`, docstring: "Fields: first_name, last_name, date_of_birth, guardian_name, guardian_email, guardian_primary_phone, guardian_secondary_phone, special_notes, team_ids, player_id, created_at") has a full guardian-contact block — `guardian_name`, `guardian_email`, `guardian_primary_phone`, `guardian_secondary_phone` — constructed on create at `backend/routes/players.py:108-119` and importable via CSV (`backend/routes/players.py:24-34`). This is explicitly a **different, older concept from `participants`**: the code comment at `firebase_service.py:150-151` states "A separate collection from 'players' — players stores a guardian's contact phone for a roster entry, not a self-owned WhatsApp identity." `players` is a guardian-holds-the-contact-details roster entry (no WhatsApp identity of its own); `participants` (Phase 2) is a self-owned WhatsApp identity with no guardian/contact fields at all today. These two collections are not currently linked (no cross-reference field observed in either schema).

**Conclusion for Section 2**: every `admin_users` record has a reliable email (usable via the existing Resend integration), but no WhatsApp number, and no role reliably maps to "the person who handles safeguarding." The Organisation record has no contact field. There is no designated-safeguarding-contact concept anywhere — but the `players` collection's guardian-contact fields are a direct, already-proven precedent for the shape such a field would take, just attached to the wrong (legacy) collection today.

---

## 3. Where an escalation would be detected

### The inbound message path (participant, text message)

Entry point (webhook): `POST /api/whatsapp-cloud-webhook`, function `whatsapp_webhook` (`backend/app.py:246-247`). For a text message it calls `ConversationService.handle_incoming_message(from_number, message_text, message_id)` at `backend/app.py:321-325`.

Call chain, in order, for a **participant** (not a coach) sending free text:

1. `whatsapp_webhook` (`backend/app.py:247`) — parses the Meta webhook payload, dedupes by `message_id` (`app.py:298-300`), marks the message read and shows a typing indicator (`app.py:307,312`), then calls `handle_incoming_message`.
2. `ConversationService.handle_incoming_message` (`backend/services/conversation_service.py:1625-1727`) — resolves the sender:
   - `PersonService.resolve(from_number)` (`backend/services/person_service.py:124`, called at `conversation_service.py:1633`) — looks up the phone across both the `coaches` and `participants` collections and returns a person dict with `person_type`.
   - At `conversation_service.py:1650-1652`: `if person.get('person_type') != 'coach': cls._handle_participant_message(from_number, message_text, person); return` — **this is the actual participant branch**; everything below in `handle_incoming_message` (SSE push, command classification, coach-specific commands) is coach-only and is never reached for a participant.
3. `ConversationService._handle_participant_message(from_number, message_text, person)` (`conversation_service.py:1761-1794`) — the real participant entry point:
   - `cls._classify_command(text_lower)` (`:1670`/`:1773`, defined `:1586`) — checks for `/help`, `/reset`, etc.
   - `cls._is_allowed(action, 'participant')` (`:1598`) — permission gate against `COMMAND_PERMISSIONS`.
   - For ordinary free text (the safeguarding-disclosure case), falls to the `else` branch (`:1781-1790`) and calls `cls.generate_response(phone, user_message, org_id, person_name, person_id, person_type='participant')`.
   - Immediately after, sends the reply: `WhatsAppService.send_message(phone_number=from_number, message_text=response)` (`:1792`).
4. `ConversationService.generate_response` (`conversation_service.py:717-803`) — builds AI context and calls Gemini:
   - `cls.get_conversation_history(phone, limit=5)` (`:729`, defined `:428`)
   - `cls.load_rag_context(org_id)` (`:734`, defined `:538`)
   - `cls.load_person_context(person_id, org_id, person_type)` (`:738`, defined `:690`)
   - `cls._terminology_for(org_id)` (`:745`, defined `:699`)
   - `cls.get_ai_persona_prompt(org_id, person_type)` (`:754`, defined `:382`)
   - `GeminiService.generate_custom_message(context)` (`:790`) — **this is the actual AI call that produces the reply text.**
   - `cls.strip_markdown(response)` (`:793`, defined `:471`)
   - `cls.save_message(phone, 'user', user_message)` and `cls.save_message(phone, 'assistant', clean_response)` (`:796-797`, defined `:498`) — **the raw participant text is persisted here, after the AI reply has already been generated but before it is sent.**

### Best insertion point

**`ConversationService._handle_participant_message`, immediately after `text_lower`/`person_name`/`org_id` are resolved and before the `action`/`response` branching (`conversation_service.py:1770-1781`, i.e. right after line 1773's `_classify_command` call).**

Why this point specifically:
- It already has the raw, un-truncated `message_text`, the resolved `person` dict (name, `org_id`, `person_id`), and confirms `person_type == 'participant'` — everything a screening check would need, with zero additional lookups.
- It runs synchronously and unconditionally for every participant text message, before the AI reply is generated or sent — a screening call placed here can run **alongside** the existing flow (e.g., fire off a classification and, on a hit, dispatch a notification) without touching the `response = cls.generate_response(...)` / `WhatsAppService.send_message(...)` lines at all. The existing reply path is completely undisturbed.
- It is strictly better than instrumenting inside `generate_response` (`:717`) itself, because `generate_response` is shared by both coaches and participants (`person_type` is just a parameter) — inserting there means every call site needs a `person_type` guard, whereas `_handle_participant_message` is already participant-only by construction.
- It is better than the webhook layer (`app.py:321`) because that layer doesn't yet know whether the sender is a coach or a participant — that resolution only happens inside `handle_incoming_message`.

### Message persistence

Yes — inbound participant text and the AI's outbound reply are both persisted, in Firestore, via `ConversationService.save_message` (`conversation_service.py:498-516`):

```
db.collection('conversations').document(phone_key).collection('messages').add(message_data)
```

`phone_key` is the sender's phone number with `+`, spaces, and `-` stripped (`:503`, same normalization as `get_conversation_history:443`) — **not** org-scoped or participant-ID-scoped, just phone-number-keyed. Stored fields: `role` (`'user'`/`'assistant'`), `content`, `timestamp` (`datetime.now(timezone.utc)`), `message_id` (a freshly generated UUID, unrelated to the WhatsApp message ID) — `conversation_service.py:506-511`.

**There is no TTL, expiry, or retention policy of any kind on this collection.** No cleanup job references `conversations` anywhere in `backend/services/scheduler_service.py` or elsewhere. Messages are kept indefinitely until manually deleted. `get_conversation_history` only reads the most recent 5-10 for context (`:428`, `limit=10` default, called with `limit=5` at `:729`) — that's a read-side cap, not a retention policy; older messages remain in Firestore.

---

## 4. The participant age and consent fields

### Current `participants` collection schema

Defined at `backend/services/firebase_service.py:148-154` (comment block) and constructed on create at `firebase_service.py:156-173`:

```python
participant_data = {
    **data,
    'org_id': org_id,
    'active': data.get('active', True),
    'created_at': now,
    'updated_at': now,
}
```

Fields actually present, confirmed end-to-end: **`org_id`, `name`, `phone_number`, `active`, `created_at`, `updated_at`.** That is the complete schema. **There is no `age`, `date_of_birth`, `dob`, or any consent-related field on `participants` today.** (Contrast with the unrelated legacy `players` collection, which does have `date_of_birth` and guardian-contact fields — see Section 2.)

### Validation on create/update — `backend/routes/participants.py` (full file, 204 lines)

- **Create** (`POST`, `create_participant`, `:72-124`): only `name` is required and validated non-empty (`:81-89`). `phone_number`/`phone` is optional, normalized via `normalize_phone_for_matching` (`utils/phone.py`) with a permissive fallback for non-SA numbers if normalization fails (`:100-106`, comment explains this was a deliberate fix — SA numbers get canonical form, others get strip-only). `active` is optional, cast to bool if present (`:108-109`). Input is built into a plain dict (`:96-109`) and passed to `FirebaseService.create_participant(org_id, participant_data)` — **there is no Pydantic model or schema class; validation is manual, field-by-field, inline in the route function.**
- **Update** (`PUT`, `update_participant`, `:126-175`): whitelist at `:141` — `allowed_fields = ['name', 'phone_number', 'phone', 'active']`. Phone fields get normalized the same way (`:144-147`). **This route-level whitelist is not the only enforcement point** — `FirebaseService.update_participant` (`firebase_service.py:208-224`) applies its own, authoritative whitelist at `:218`: `allowed_fields = ['name', 'phone_number', 'active']` (note: no bare `'phone'` here — it's normalized to `phone_number` before reaching this layer). Any field not in this second list is silently dropped even if it slipped past the route layer.

### What would need to change to add `age`/`date_of_birth` and a consent record

Concretely, four points, all in the two files above:

1. `backend/routes/participants.py:96-109` (`create_participant`) — add the new field(s) into the `participant_data` dict construction, with whatever validation (e.g. date parsing, minimum-age check) the design calls for.
2. `backend/routes/participants.py:141` (`update_participant`'s `allowed_fields`) — add the new field name(s).
3. `backend/services/firebase_service.py:218` (`update_participant`'s `allowed_fields`) — **this is the one that actually matters for whether an update sticks**; must be updated or the field will never persist via update, even if the route-level whitelist allows it through.
4. A consent *record* (as opposed to a flat boolean field) would likely want its own sub-structure or subcollection (e.g. `consent_given_at`, `consent_given_by`, `consent_method`) — there is no existing precedent for a structured consent object anywhere in this codebase to model it on; the closest analog is the flat `guardian_*` fields on `players` (Section 2), which are flat strings, not a record with provenance/timestamp.

There is no Pydantic/marshmallow schema class to update anywhere in this path — every validation and whitelist point above is a plain Python list or manual `if field in data` check.

**Seed script**: `backend/scripts/seed_staging_test_data.py:214-223` constructs participant documents directly against Firestore (`db.collection('participants').document(doc_id).set({...})`), with exactly the current field set (`name`, `phone_number`, `active`, `org_id`, `created_at`, `updated_at`, `:216-221`). It would need updating to include the new field(s) **only if** the field is meant to be required or the seed data is meant to exercise the new logic (e.g. an isolation test or age-gating check reading it) — nothing about the current schema forces the seed script to change for an optional field to work.

**The 14 org-isolation tests** — `backend/tests/test_org_isolation.py`: `GET_ALL_METHODS` parametrize list has 9 cases (`:103-113`, includes `get_all_participants` at `:107`), `SINGLE_DOC_GETTERS` has 3 cases (`:175-179`, does not include participants — it uses the reversed-argument getters), plus two standalone tests: `test_get_participant_blocks_cross_org_id_guess` (`:205-228`) and `test_load_rag_context_isolates_by_org` (`:235`) — 9+3+1+1 = 14, matching. **None of these 14 tests assert an exact field set on a participant document** — they check `org_id` equality/presence (`:195,221`) and cross-org `None` returns (`:199,225`). Adding a new field to `participants` would **not** break any of these 14 tests; they would continue to pass unchanged. They would need updating only if the new escalation-detection logic itself needed an isolation proof (e.g. a new `safeguarding_escalations` collection — see Section 5).

---

## 5. Risks and constraints

### If the escalation notification itself fails to send, would anyone find out?

**No — not with the patterns currently in place, unless the design deliberately breaks from them.** Concrete evidence from existing code, not speculation:

- `email_service.py:_send` (`:71-90`): a missing API key logs a `WARNING` and returns; a failed Resend API call is caught and logged at `ERROR` (`:89-90`). **Neither path re-raises.** Every existing caller (`routes/auth.py:214,322,388`) has no idea whether the email actually sent — this is exactly the shape a new "send safeguarding escalation email" would inherit if built the same way.
- `WhatsAppService.send_message` (`whatsapp_service.py:12-86`) never raises on failure; it returns `{"success": False, "error": ..., ...}` (`:80-86`). Callers must explicitly check `.get('success')`. In `_handle_participant_message` (`conversation_service.py:1792-1794`), a failed send is only `logger.error(...)`'d — no SSE push, no retry, no admin alert. Compare to the coach path (`handle_incoming_message:1712-1717`), which at least pushes an SSE event with preview `"[send failed]"` (`:1717`) — but that's only visible to an admin actively watching the Live Activity feed at that moment (Section 1), and the participant path doesn't even do that much.
- `SchedulerService`'s three jobs (`scheduler_service.py`) accumulate failures into an in-memory `errors` list per run (e.g. `:41, 120, 209`), exposed only via `GET /api/admin/scheduler/status` (wired at `routes/admin.py:309`) — an admin has to know to check that endpoint; nothing pushes it to them.

**This is precisely the pattern that steps 3b and 3c (commits `99df2dc` and `ef1008d`) were fixing** — but only in the paths they touched (`load_coach_context`/`load_rag_context` for 3b; `PersonService` cache refresh, pricing read-merge-write, pending-attendance/photo reads, conversation history reads for 3c). Their fix pattern each time was the same: stop returning a value indistinguishable from success/empty-but-fine, and either raise a typed exception the caller must handle, or inject an explicit `[SYSTEM NOTE: ...]`/log-at-ERROR signal. **Neither commit touched `email_service.py` or `WhatsAppService.send_message`'s failure handling** — those two send paths still silently swallow failures today, on `phase2-participant-identity` as of this audit. A new escalation-send call built naively on top of either would reproduce the exact class of bug steps 3b/3c were created to eliminate, unless it's deliberately built to raise/alert on failure (e.g., a second, independent channel, or a persisted "escalation record" with a `delivered` status admins can audit — see below).

### Would a new Firestore collection need its own index, and does that collide with the Phase 0 org_id isolation pattern?

**Isolation is enforced entirely in application code, not by Firestore security rules.** `firestore.rules:6-8`:

```
match /{document=**} {
  allow read, write: if true;
}
```

— open read/write for everything, with the comment "Allow all access for now (since backend uses Admin SDK which bypasses rules anyway)." So the *only* thing preventing one org from reading another org's data is that every `FirebaseService` getter takes an explicit `org_id` and applies `.where('org_id', '==', org_id)` (e.g. `get_all_participants`, `firebase_service.py:194-205`) or, for single-doc getters, fetches by ID and then checks `data.get('org_id') != org_id` and returns `None` on mismatch (e.g. `get_participant`, `:176-191`). This is exactly the pattern `test_org_isolation.py` (Section 4) proves holds across every existing collection.

**A new `safeguarding_escalations` collection would need to follow the identical pattern**: every read/write function in `FirebaseService` for it would need to take `org_id` as an explicit parameter (not trust a value from the request body — see the comment at `firebase_service.py:159-160` on `create_participant` making this exact point) and filter/verify by it, the same way every other collection does. There is nothing Firestore-security-rules-side to lean on; it is 100% on whichever new `FirebaseService` methods are written.

**Composite index**: only one composite index exists at all today — `firestore.indexes.json:3-10`, `sessions` on `(org_id ASC, date ASC)`, needed because `get_sessions_for_reminder` filters by `org_id` *and* orders/range-filters by `date` in the same query. `get_all_participants` needs no composite index because it only ever applies a single equality filter (`org_id`) with no additional `order_by`/range clause. **A new `safeguarding_escalations` collection would need its own composite index entry in `firestore.indexes.json` if and only if its query combines `org_id` equality with an `order_by` on another field** (e.g., listing an org's escalations sorted by `created_at`, which is exactly the kind of query an escalations-review screen would want) — that is the same shape of requirement the `sessions` index already exists to satisfy, so there's a direct precedent to follow, but it does not exist automatically; it would need to be added.

---

## Summary of what plainly does not exist

- No safeguarding-contact / DSL concept anywhere.
- No `contact_email`/`contact_person` field on Organisation.
- No `phone_number`/WhatsApp field on `admin_users`.
- No notification bell, toast-from-backend, or persisted notifications collection.
- No `age`/`date_of_birth`/consent field on `participants`.
- No retention policy or TTL on the `conversations` collection.
- No Firestore-security-rules-level org isolation — it is 100% application-code enforced.
- No failure-surfacing on either existing send path (email or WhatsApp) — both silently swallow send failures today.
