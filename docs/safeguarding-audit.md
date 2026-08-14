# Safeguarding Escalation Audit (Read-Only)

**Branch:** `phase2-participant-identity`
**Date:** 2026-08-14
**Scope:** What exists today that a safeguarding escalation path (participant WhatsApp → real human) could build on. No code was changed to produce this report.

Note: the audit brief assumed a FastAPI backend. It is actually **Flask** (`backend/routes/*.py` uses `flask.Blueprint`, plain dict validation — there are no Pydantic models anywhere in `backend/`). This changes how "validation" is described in section 4 below.

---

## 1. Notification channels that already exist

### Email

- **Provider:** [Resend](https://resend.com), via the `resend` Python package.
- **Service:** `backend/services/email_service.py` — the only file that sends email in this codebase.
- **Config:** `backend/config.py:46-48` — `RESEND_API_KEY`, `RESEND_FROM_EMAIL` (default `noreply@tekohq.com`). Both read from environment.
- **Send path:** all sends funnel through one private helper, `_send()` (`email_service.py:71-90`), which does `resend.Emails.send(...)` inside a `try/except`.
- **Existing uses (all transactional, all admin-facing, none participant-facing):**
  - `send_invite_email` (`email_service.py:93-109`) — called from `routes/auth.py:319-321` when a super_admin/location_admin invites a new admin/coach.
  - `send_password_reset_email` (`email_service.py:112-127`) — called from `routes/auth.py:214`.
  - `send_welcome_email` (`email_service.py:130-142`) — defined but not called from `routes/auth.py` in the ranges inspected; exists as an available primitive.
- **Reliability:** it is already load-bearing for password reset and admin invites, so the provider integration itself is proven. But `_send()` (`email_service.py:88-90`) only logs on failure — see Section 5, this is the same silent-swallow pattern step 3b/3c fixed elsewhere in the codebase, and it is still present here, unfixed.
- **No API key configured:** falls back to `logger.warning(...)` and does not send (`email_service.py:73-78`) — i.e., in an environment without `RESEND_API_KEY`, every email silently becomes a log line only.

### Outbound WhatsApp (outside a live conversation reply)

- **Service:** `backend/services/whatsapp_service.py` — `WhatsAppService.send_message()` (`whatsapp_service.py:12-86`) and `send_template_message()` (`whatsapp_service.py:134-199`) are the two send primitives; both take a bare `phone_number` and are not scoped to any collection (coach, participant, or anything else) — either can be pointed at any phone number.
- **Broadcasts:** `routes/broadcasts.py:70-` (`POST /` broadcast-send route) is admin-triggered, sends to `data['recipient_ids']`, which are **coach IDs only** — `routes/broadcasts.py:136-137` batch-fetches `FirebaseService.get_all_coaches(org_id)`, not participants. There is no broadcast-to-participants path today.
- **Scheduler:** `backend/services/scheduler_service.py` runs periodically (registered as an APScheduler job in `app.py:79-101`, or callable via `POST /api/scheduler/mark-missed`, `app.py:179-188`). It sends **session check-in reminders to coaches** (`scheduler_service.py:108` via `send_check_in_reminder`, and `:202` via `send_message`) — again, coach-only, not participant-facing, and not a generic "notify a human" mechanism.
- **Conclusion:** the underlying "send a WhatsApp message to an arbitrary phone number" primitive (`WhatsAppService.send_message`) is reusable and already proven reliable (it's the same function used for every AI reply), but nothing today calls it to notify an *admin*. There is no admin phone number stored anywhere to call it with (see Section 2).

### In-app / dashboard alert surface

- **The only real-time surface is the SSE live activity feed.** `backend/routes/sse.py` — `push_event()` (`sse.py:19-38`) appends to a process-local, **in-memory** list (`_event_list`, `sse.py:12`), capped at `_MAX_EVENTS * 2 = 400` before trimming (`sse.py:36-38`). No database backing, no persistence across a server restart, no multi-process fan-out.
- Frontend consumer: `frontend/src/components/schedule/LiveActivityFeed.tsx` — an `EventSource` subscription (`LiveActivityFeed.tsx:34-46`) that only renders while the Schedule page is open, keeps at most 50 events client-side (`LiveActivityFeed.tsx:36`), and has **no unread counter, badge, or persistence** of any kind. A repo-wide search for `unread`, `alert_count`, `notificationCount` in `frontend/src` returned nothing.
- `components/ui/badge.tsx` exists but is a generic styling primitive (used for status pills like role/active labels), not a notification-count badge — no code path feeds it a count.
- **Critical gap found in the SSE feed itself:** `push_event()` is only called from the **coach** branch of `handle_incoming_message` (`backend/services/conversation_service.py:1659` `message_received`, `:1714`/`:1717` `response_sent`). `_handle_participant_message` (`conversation_service.py:1761-1795`, the entire participant-message path) **never calls `push_event`**. A grep of the whole file for `push_event` confirms all 7 call sites (`conversation_service.py:1028, 1235, 1423, 1659, 1714, 1717`) are coach-only or attendance/check-in/photo flows. **Participant messages do not appear on the Live Activity Feed at all today** — the one real-time surface that exists doesn't cover participants, let alone flag a disclosure of harm.

---

## 2. Who would receive an escalation

### `admin_users` collection

- CRUD lives in `backend/services/firebase_service.py:869-953`.
- Fields actually stamped on create (`firebase_service.py:872-881`, docstring at `:873-876`): `name`, `email`, `password_hash`, `role`, `status`, `org_id` (passed via `data`), `created_at`.
- **`email` is present and used as the lookup key** — `get_admin_by_email()` (`firebase_service.py:910-917`) does `.where('email', '==', email)`, and it's this method that both login (`routes/auth.py:91`) and the invite flow (`routes/auth.py:308`) rely on. So yes — every admin has a contactable email today, and the email-send infrastructure already targets it.
- **No phone number field.** A repo-wide grep for `phone` near `admin` in `services/firebase_service.py` returned nothing. Admins cannot be reached by the WhatsApp channel today — only email.
- **Roles in actual use** (per `routes/auth.py:288-296`, the invite endpoint): `super_admin`, `location_admin`, `coach`. Note `routes/admin.py:75` (`allowed_roles = ['admin', 'superadmin', 'viewer']`) uses a **different, inconsistent role vocabulary** in a separate admin-management route — worth flagging as a pre-existing inconsistency, out of scope to fix here.
- `get_all_admins_by_org(org_id)` (`firebase_service.py:946-953`) already exists and would be the natural lookup for "who at this org should be notified" — it returns all admins for an org with passwords stripped, no role filter applied.

### Organisation record

- CRUD in `firebase_service.py:1051-1098+`; fields stamped on create per the docstring at `:1082-1088`: `name`, `slug`, `type`, `terminology`, `ai_persona_prompt`, `country`, `supported_languages`, `is_active`, `created_at`.
- Admin-editable whitelist: `routes/organisations.py:79` — `allowed_fields = ['name', 'type', 'terminology', 'ai_persona_prompt', 'country', 'supported_languages']`.
- **There is no contact-person or contact-email field on the Organisation record, anywhere, today.** Neither the create docstring nor the update whitelist mentions one.

### Designated safeguarding contact

- **Does not exist as data anywhere in this codebase.** It exists only as a **sentence the AI is told to say**. `backend/services/conversation_service.py` — the participant persona prompt for the `sports` org type instructs the AI: *"Don't provide legal or safeguarding-incident advice beyond general awareness — refer serious concerns to the organisation's designated safeguarding contact"* (`conversation_service.py:154`). The same sentence (worded slightly differently per org type) appears at `:194`, `:219`, `:284`, `:349`.
- This is purely a **prompt instruction to the AI's reply text** — it tells the participant, in the chat, to go contact someone. It does not: look up who that contact is, notify anyone, flag the conversation, or persist any record that a safeguarding-relevant message occurred. The referenced "designated safeguarding contact" is not a field, a document, or a lookup anywhere in `backend/` — it is a phrase in a string constant, and the org never actually configured who it refers to.
- `tests/test_participant_persona.py:88-94` (`test_participant_persona_has_safeguarding_line`) only asserts the word "safeguarding" appears in the generated prompt text — it does not (and cannot, since nothing exists) test that an actual contact is reachable.

---

## 3. Where an escalation would be detected

### Exact inbound trace, participant path (function names, in call order)

1. `ConversationService.handle_incoming_message(from_number, message_text, message_id)` — `conversation_service.py:1625`
2. `PersonService.resolve(from_number)` — called at `conversation_service.py:1633`, resolves the sender to a coach or participant record.
3. Branch: `person.get('person_type') != 'coach'` (`:1650`) →
4. `ConversationService._handle_participant_message(from_number, message_text, person)` — `conversation_service.py:1761`, called at `:1651`
5. Inside `_handle_participant_message`: `ConversationService._classify_command(text_lower)` (`:1773`) and `ConversationService._is_allowed(action, 'participant')` (`:1775`) — routes `/help`, `/reset`, declined-command replies, or free text.
6. For free text (the `qa` action, i.e. anything that isn't a slash command): `ConversationService.generate_response(phone, user_message, org_id, person_name, person_id, person_type='participant')` — called at `:1783`, defined at `:717`.
7. Inside `generate_response`: `get_conversation_history` (`:729`) → `load_rag_context` (`:734`) → `load_person_context` → `load_participant_context`/`load_person_context` (`:738`) → `_terminology_for` (`:745`) → `get_ai_persona_prompt` (`:754`) → `GeminiService.generate_custom_message(context)` (`:790`, the actual AI call) → `strip_markdown` (`:793`) → `save_message` x2 (`:796-797`, saves both the participant's message and the AI's reply) → returns `clean_response`.
8. Back in `_handle_participant_message` (`:1792`): `WhatsAppService.send_message(phone_number=from_number, message_text=response)` — the actual outbound send, the end of the reply path.

### Best insertion point

**Inside `_handle_participant_message` (`conversation_service.py:1761-1795`), specifically around the `generate_response` call at line 1783** — either immediately before it (on the raw `message_text`) or immediately after it (with both the participant's message and the AI's own reply available). At that point in the call stack you already have, in scope: the raw inbound text, `person_name`, `person_id`, `org_id`, and (after the call) the AI's reply text — everything needed to run a harm-disclosure check and fire an escalation, as a side call that does not touch or alter the existing `response` variable or the `WhatsAppService.send_message` call at line 1792. This is the one place participant messages are both fully resolved (org/person context known) and not yet irreversibly "just replied to and forgotten."

The alternative — inserting inside `generate_response` itself (`:717`) — would work equally well for content inspection but is shared code with the coach path, so a participant-specific check would need an extra `person_type == 'participant'` branch inside a function that today has no such branching.

### Message persistence

- Yes — `ConversationService.save_message(coach_phone, role, content)` (`conversation_service.py:498-516`) writes to Firestore at `conversations/{phone_key}/messages` (`:513`), one document per message, called for both `'user'` and `'assistant'` roles (`:796-797`). This applies to participants exactly as it does coaches — `phone_key` is just the sender's own normalized number, and `_handle_participant_message` reaches `save_message` via the same `generate_response` call.
- **Retention: indefinite, with no configured limit.** A repo-wide grep for `ttl`/`TTL`/`retention` in `backend/` found no Firestore TTL policy, no cleanup job, and no expiry logic touching the `conversations` collection. `firestore.rules` and `firestore.indexes.json` contain no reference to `conversations` or `messages` at all (see Section 5 — `firestore.rules` doesn't police any collection). There is nothing in this repository that ever deletes a stored message.
- `save_message` itself silently swallows write failures — `except Exception as e: logger.error(...)` with no re-raise (`conversation_service.py:515-516`) — so a save failure is invisible to the caller (see Section 5).

---

## 4. The participant age and consent fields

### Current `participants` collection schema (as actually built)

From `firebase_service.py:150-173` (docstring + `create_participant`) and confirmed by the seed script (`backend/scripts/seed_staging_test_data.py:215-222`):

```
{
  id,               # Firestore doc id
  name,             # string, required
  phone_number,     # string, normalized via normalize_phone_for_matching
  org_id,           # stamped server-side from the request's org context, never client-supplied
  active,           # bool, default True
  created_at,       # server timestamp
  updated_at,       # server timestamp
}
```

**No age, date_of_birth, or consent-related field exists on `participants` anywhere in this codebase.** A repo-wide case-insensitive grep for `date_of_birth`, `dob`, `age`, `consent` across `backend/` found matches only on the unrelated `players` collection (`routes/players.py:28,111,156,310`, `firebase_service.py:70,77,124,129,518` — guardian-linked roster entries, a different collection from `participants`) and on `coaches` (`routes/coaches.py:132,177` — `dob` as an optional profile field). Neither `age` nor `consent` appears in the `participants` code path, in the seed script, or in any test.

### Validation on create/update (`routes/participants.py`)

There are **no Pydantic models** — this is Flask, and validation is hand-written dict-checking directly in the route handlers.

- **Create** (`routes/participants.py:72-124`, `POST /`):
  - Requires `data['name']` present and non-empty after `.strip()` (`:81-89`).
  - `phone_number`/`phone` optional; if present, normalized via `normalize_phone_for_matching` (`:104-106`).
  - `active` optional, coerced to `bool` if present (`:108-109`).
  - Everything else in the request body is silently dropped — `participant_data` is built as an explicit dict literal (`:96-98`) plus the two conditional fields above; there is no passthrough of arbitrary request fields.

- **Update** (`routes/participants.py:126-175`, `PUT /<participant_id>`):
  - Route-level whitelist: `allowed_fields = ['name', 'phone_number', 'phone', 'active']` — `routes/participants.py:141`.
  - **Second, independent whitelist inside the service layer**: `firebase_service.py:218` — `allowed_fields = ['name', 'phone_number', 'active']` inside `update_participant()`. Note this one omits the bare `'phone'` alias that the route layer allows — the route normalizes `'phone'` into `'phone_number'` before calling the service (`routes/participants.py:145-147`), so the two lists are consistent in effect, but they are two separately-maintained lists that must be kept in sync by hand.
  - No per-field validators (no regex, no length limit, no type-check beyond the `bool()` cast on `active`) beyond phone normalization.

### What would need to change to add `age`/`date_of_birth` + a consent record

Plainly, based on the above:

1. **`routes/participants.py`**: add the new field name(s) to the `create_participant` handler's field-building logic (currently `:96-109`) and to the update `allowed_fields` list at `:141`.
2. **`firebase_service.py`**: add the same field name(s) to the `update_participant` `allowed_fields` list at `:218` (this is a **second, separate** list from the route-layer one — both need editing, or they will silently diverge again). `create_participant` (`:156-173`) itself needs no change since it already does `**data` passthrough (`:165`) — whatever the route builds into `participant_data` is stored as-is; only the route's explicit field-building block would need to add the new key(s).
3. **No Pydantic model exists to update** — there is nothing else validating shape beyond the two whitelists above and the manual checks in the route handler.
4. **`backend/scripts/seed_staging_test_data.py`**: yes, it would need updating. `seed_staging_test_data.py:215-222` builds participant documents with an explicit, fixed field set (`name`, `phone_number`, `active`, `org_id`, `created_at`, `updated_at`) — it does not read from a schema definition, so a new field would not appear in seeded data unless this literal dict is edited.
5. **`backend/tests/test_org_isolation.py`** (14 tests total: 9 parametrized `get_all_*` cases + 3 parametrized single-doc-getter cases + `test_get_participant_blocks_cross_org_id_guess` + `test_load_rag_context_isolates_by_org` = 14, confirmed by counting `GET_ALL_METHODS`/`SINGLE_DOC_GETTERS` entries plus the two standalone `def test_...` functions):
   - This file **does not construct participant documents itself** — it imports `_doc_ids` from `seed_staging_test_data.py` (`test_org_isolation.py:57`) and only reads already-seeded staging data through `FirebaseService` methods.
   - It is **schema-agnostic with respect to any new field**: every assertion in it checks only `record.get('org_id')` and `record.get('id')` (e.g. `test_org_isolation.py:144-151`, `:225-227`) — it never inspects `name`, `phone_number`, or any other field content.
   - **Conclusion: adding `age`/`date_of_birth`/consent would not require editing `test_org_isolation.py`** — it would only require editing `seed_staging_test_data.py` if you want the new field present in realistic seeded test data (not required for isolation tests to keep passing, since they don't look at it).

---

## 5. Risks and constraints

### If an escalation notification itself failed to send — would anyone find out? No, not with the current send primitives as they exist today.

Every notification-sending function inspected in this audit follows the same pattern: **log the failure, swallow the exception, return normally.**

- `email_service._send()` — `services/email_service.py:89-90`: `except Exception as e: logger.error(...)`. No re-raise, no return value indicating failure to a caller that might act on it, no alerting.
- `ConversationService.save_message()` — `conversation_service.py:515-516`: identical pattern; a failed write to `conversations/{phone}/messages` is invisible to whatever called `save_message`.
- `WhatsAppService.send_message()` (`whatsapp_service.py:68-86`) is the one exception in this group — it *does* return a structured `{"success": False, "error": ..., ...}` dict rather than swallowing silently, and both call sites checked in this audit (`conversation_service.py:1712-1717`, `:1793-1794`) do check `result.get('success')` and log at ERROR on failure. But even there, "log at ERROR" is the entire consequence — nothing pages a human or retries.

This is precisely the class of bug that **step 3b** (`99df2dc`) and **step 3c** (`ef1008d`) were written to eliminate elsewhere in this codebase. Their commit messages are explicit about the standard they set: failures must "log at ERROR," must be distinguishable from an empty/normal result (step 3c items 4-6, e.g. `PendingStateReadError` replacing a silent `None` return), and a degraded state must surface as a system-level signal rather than disappearing. Per `ef1008d`'s message: *"Six failures... that degraded silently instead of loudly."*

**If a safeguarding escalation were built by directly reusing `email_service.send_*` or the existing WhatsApp/save patterns without change, it would reintroduce exactly the bug class 3b/3c fixed — except for the single highest-stakes notification in the system.** A failed escalation email today would produce one `logger.error()` line and nothing else: no retry, no fallback channel, no dashboard indicator, no second attempt. Given Section 1's finding that the SSE feed doesn't even cover participant messages, there is currently **no existing surface that would catch a silently-failed escalation** — not the live feed (participant-blind), not email (fire-and-forget), not WhatsApp (logged, not alerted).

### Would escalation records need their own Firestore collection and index — and does that collide with the org_id isolation pattern?

- Yes, a new collection would be the natural fit (nothing in the existing schema — `conversations`, `participants`, `admin_users` — has a slot for "flagged incident" records).
- **`firestore.rules` (repo root) grants unconditional access to every collection**: `match /{document=**} { allow read, write: if true; }` (`firestore.rules:6-8`), with the comment *"since backend uses Admin SDK which bypasses rules anyway."* This means **org isolation in this codebase is enforced entirely in application code**, not by Firestore security rules — every `get_all_*`/`get_*` method in `firebase_service.py` does its own `.where('org_id', '==', org_id)` filtering and/or post-fetch ownership check (e.g. `get_participant`, `firebase_service.py:176-191`, checks `data.get('org_id') != org_id` after fetching by bare doc ID).
- **This means a new escalation collection would need to hand-implement the exact same discipline** every other collection does: stamp `org_id` server-side on write (never trust it from the request body — see the comment at `firebase_service.py:159-160` on `create_participant` making this explicit), filter by `org_id` on every list/get, and add itself to `test_org_isolation.py`'s `GET_ALL_METHODS` list (`test_org_isolation.py:103-113`) to get the same automated cross-org leak test the other 9 collections have. There is no shared enforcement layer to inherit this from automatically — it is a pattern to be manually replicated correctly, not a constraint imposed by the platform.
- On the Firestore index side: `firestore.indexes.json` currently has no entries related to any escalation concept (checked — no `conversations`/`messages` entries either). A new collection queried by `org_id` alone would very likely not need a composite index (Firestore auto-indexes single-field equality), but if escalations need `org_id` + a status/severity ordering (e.g. "unresolved, most recent first"), that composite index would need to be added the same way the step-3b fix added one for `sessions` (`firestore.indexes.json`, per `99df2dc`'s diff) — including deploying it, which that commit's message notes required direct Admin API calls because the `firebase`/`gcloud` CLI auth had expired at the time.
