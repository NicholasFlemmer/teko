# Deploying the frontend

The frontend image is built from source by `frontend/Dockerfile`. It is a
multi-stage build: `npm ci` installs from `package-lock.json` (the only
lockfile in this directory — see "Lockfile" below), `vite build` produces
`dist/`, and only that `dist/` output is copied into the final `nginx:alpine`
image. Nothing from a developer's local machine (`node_modules/`, an existing
local `dist/`, `.env`) can leak into the image — `.dockerignore` excludes all
of it, and `.gcloudignore` excludes `.env`/`.env.*` and `dist/` from what
even gets uploaded to Cloud Build.

## Build-time variables

`VITE_API_URL` and `VITE_GOOGLE_MAPS_API_KEY` are Vite build-time variables:
they get baked as literal strings into the compiled JavaScript bundle, not
read at container runtime. That means they must be supplied as **Docker
build args**, not as Cloud Run environment variables — setting them with
`gcloud run services update --set-env-vars` after the fact does nothing,
because the bundle is already compiled.

The Dockerfile enforces this: the build stage checks both args and **fails
the build** if either is empty or unset, rather than letting `vite build`
silently fall back to the `http://localhost:5002` default hardcoded in
`src/services/api.ts`. That fallback is what shipped a production bundle
pointed at nothing in the past — see the April 2026 audit.

## Deploying

### Verified path: build locally, push, then point Cloud Run at the image

```bash
cd frontend

docker build \
  --build-arg VITE_API_URL=https://teko-backend-218004920355.us-central1.run.app \
  --build-arg VITE_GOOGLE_MAPS_API_KEY=<your-maps-api-key> \
  -t us-central1-docker.pkg.dev/teko-236ad/<REPO>/teko-frontend:<TAG> .

docker push us-central1-docker.pkg.dev/teko-236ad/<REPO>/teko-frontend:<TAG>

gcloud run deploy teko-frontend \
  --image us-central1-docker.pkg.dev/teko-236ad/<REPO>/teko-frontend:<TAG> \
  --region us-central1 \
  --project teko-236ad
```

This is the path exercised and confirmed working end-to-end (see the build
report accompanying this commit).

### One-step alternative: `gcloud run deploy --source`

Cloud Run's source deploy also builds from this Dockerfile directly and,
per Google's documented behavior, forwards `--set-build-env-vars` as Docker
`--build-arg` values when a Dockerfile (rather than buildpacks) drives the
build:

```bash
cd frontend

gcloud run deploy teko-frontend \
  --source . \
  --region us-central1 \
  --project teko-236ad \
  --set-build-env-vars=VITE_API_URL=https://teko-backend-218004920355.us-central1.run.app,VITE_GOOGLE_MAPS_API_KEY=<your-maps-api-key>
```

This has not been exercised as part of this change (no deploy was run) —
verify the build-arg forwarding behavior against current Cloud Run docs
before relying on it, or prefer the verified `docker build` path above.

### If either build arg is missing

The build fails immediately in the build stage with a clear error
(`ERROR: VITE_API_URL build arg is required ...` /
`ERROR: VITE_GOOGLE_MAPS_API_KEY build arg is required.`) and no image is
produced. There is no partial or fallback build.

## Lockfile

`frontend/` used to carry both `bun.lockb` and `package-lock.json`. Only one
lockfile can be authoritative — two lockfiles can resolve the same
`package.json` to different transitive dependency versions, and there is no
way to know which one actually produced any given historical build.
`package-lock.json` is the one documented in this project's own README
(`npm i`) and `DEPLOYMENT.md` (`npm run build`), and the only one with any
corresponding install evidence on disk. `bun.lockb` has been deleted.
`npm ci` (not `npm install`) is used in the Dockerfile so the lockfile is
authoritative and the build fails outright on any drift from
`package.json`, rather than silently re-resolving.

## VITE_GOOGLE_MAPS_API_KEY is not a secret — treat it as public

Because it is a Vite build-time variable, `VITE_GOOGLE_MAPS_API_KEY` is
compiled directly into the publicly served JavaScript bundle. Anyone can
read it out of the deployed site's assets. This is expected and is how
Google's own Maps JavaScript/Embed APIs are meant to be used client-side —
the key is not a bearer credential.

Do **not** try to keep it secret (Secret Manager, `.env` files kept out of
git, etc. do not protect it once it's built into a public bundle it will
still be readable). Instead, restrict it in the Google Cloud Console:

- **APIs & Services → Credentials** → select the key → **Application
  restrictions** → **HTTP referrers (web sites)** → add the production
  frontend origin(s) (e.g. `https://teko-frontend-218004920355.us-central1.run.app/*`
  and any custom domain).
- Additionally restrict it under **API restrictions** to only the specific
  Maps APIs this app uses (Maps Embed API), so even a copied key is
  useless for anything else.

Referrer restriction, not secrecy, is the actual control here.
