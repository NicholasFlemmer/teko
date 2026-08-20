# Login bugs found (2026-08-20)

Two frontend bugs found while diagnosing an admin login failure. Documented here, not fixed — see "Blocker" below for why.

## Bug 1: Username field label/placeholder mismatch

**Location:** `frontend/src/pages/Login.tsx:68-73`

The field is labeled "Username" with placeholder "Enter your username." The backend authenticates by looking up `admin_users` in Firestore via an exact match on the `email` field, using the submitted string verbatim (see backend hardening item below). Anything shorter than the full email address — e.g. a bare username — can never match a stored document, so login silently fails for anyone who types what the label tells them to type.

**Proposed fix:** Change the label to "Email" and the placeholder to something like "you@example.com". Optionally change `type="text"` to `type="email"` on the `Input` for native browser validation. No backend change needed — the backend already expects a full email in the `username` field of the login payload.

## Bug 2: Login page swallows the real error and can silently do nothing

**Location:** `frontend/src/services/api.ts:52-60`

The shared `request()` helper used by every API call intercepts **any** 401 response globally, before the response body is ever parsed:

```js
if (response.status === 401) {
  removeToken();
  if (!isRedirectingTo401) {
    isRedirectingTo401 = true;
    window.location.href = '/login';   // hard navigation
  }
  throw new Error('Unauthorized');
}
```

This runs for the login request's own 401 (bad credentials), not just for expired-session 401s on other endpoints. Two consequences:

1. The backend's actual `{'error': '...'}` body is discarded before it ever reaches `Login.tsx`'s message-mapping logic (`Login.tsx:31-42`), so the UI can only ever show a generic "Invalid username or password," regardless of what the backend actually said.
2. `window.location.href = '/login'` is a full-page navigation, fired from the login page itself while its own login attempt is still in flight. This races the pending promise: when the navigation wins the race, the component unmounts before `setError` runs, so the page appears to do nothing at all.

**Proposed fix:** Exempt the login endpoint's own request from this global 401 handler — e.g. check `endpoint !== '/api/auth/login'` (or pass an `opts.skipAuthRedirect` flag from `authAPI.login`) before triggering `removeToken()` / the redirect / the generic throw, and instead fall through to the normal `!response.ok` branch below so `data.error` reaches the caller. `Login.tsx`'s existing message-mapping logic already handles the resulting error strings correctly and needs no change.

## Blocker: deploying this fix is a separate, larger piece of work

Applying either fix requires deploying `frontend`. That service has not been deployed since 2026-04-13, its `Dockerfile` has no build step, and the currently running image was shipped from an unverified disk state. Getting a fix live therefore isn't a two-line patch-and-deploy — it requires first sorting out the frontend's build/deploy pipeline. Treat that as its own piece of work, tracked separately from these two bug writeups.

## Backend hardening item (separate from the two bugs above)

`FirebaseService.get_admin_by_email` (`backend/services/firebase_service.py:933-940`) performs an exact string match against the stored `email` field:

```python
docs = db.collection('admin_users').where('email', '==', email).limit(1).stream()
```

No lowercasing or trimming is applied to the incoming value (nor is any applied in `login()` before calling it). A stored or submitted email with different casing, or with leading/trailing whitespace, will silently fail to match — same failure mode as Bug 1, but on the backend, and not fixed by relabeling the frontend field.
