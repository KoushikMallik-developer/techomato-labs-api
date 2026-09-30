# Techomato Labs API

[![CI](https://github.com/KoushikMallik-developer/techomato-labs-api/actions/workflows/ci.yml/badge.svg)](https://github.com/KoushikMallik-developer/techomato-labs-api/actions/workflows/ci.yml)

REST API behind the [Techomato Labs](../techomato-labs-app) circuit simulator: accounts, projects, folders, the
community gallery (likes, comments, follows, remixes) and admin moderation.

| Concern | Choice |
| --- | --- |
| Framework | Django 5.1 + Django REST Framework |
| Database | PostgreSQL 16 |
| Cache, sessions, broker | Redis 7 (separate logical DBs) |
| Background jobs | Celery (verification / password-reset emails) |
| Runtime | Docker Compose: `web` (gunicorn), `worker` (Celery), `db`, `redis` |
| Tests | pytest + pytest-django |

## Quick start (everything runs in Docker)

```bash
cp .env.example .env        # already present in this checkout; edit freely
docker compose up --build   # db + redis + web + worker
```

* API: <http://localhost:8000/api/v1/> · health check: <http://localhost:8000/api/v1/health/>
* Django admin (data browser): <http://localhost:8000/django-admin/> (sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`)
* Verification / password-reset emails are printed to the **worker** log
  (`docker compose logs -f worker`) while `EMAIL_BACKEND` is the console backend.

On every start the `web` container applies migrations, collects static files, creates/updates the admin account from
`ADMIN_EMAIL`/`ADMIN_PASSWORD`, and seeds the six built-in gallery circuits (`SEED_GALLERY=true`).

Useful commands:

```bash
docker compose run --rm web pytest                 # run the test suite (needs INSTALL_DEV=true, the default)
docker compose run --rm web python manage.py shell
docker compose exec web python manage.py createsuperuser
docker compose down -v                              # stop and wipe the database/redis volumes
```

Source is bind-mounted into the containers and gunicorn reloads on change (`GUNICORN_RELOAD=true`); restart the
`worker` after editing task code (`docker compose restart worker`).

## Configuration (`.env`)

Every setting is an environment variable; `.env.example` documents them all. The most useful ones:

| Variable | Purpose |
| --- | --- |
| `DJANGO_DEBUG`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` | Core Django. The secret key is mandatory when debug is off. |
| `FRONTEND_URL` | Base URL of the SPA (CORS, CSRF, and the links in emails). |
| `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` | Origins allowed to call the API with cookies. |
| `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` / `*_SAMESITE` | Cookie flags. Use `true` + `None` when SPA and API are on different registrable domains over HTTPS. |
| `POSTGRES_*` | Database. Containers always reach it as host `db`. |
| `REDIS_URL`, `REDIS_*_DB` | Redis base URL and the DB numbers used for cache / sessions / broker / results. |
| `EMAIL_*`, `DEFAULT_FROM_EMAIL` | Outgoing mail. Switch `EMAIL_BACKEND` to the SMTP backend for real delivery. |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Moderator account synced on each start (blank = skip). **Dev defaults only – change them.** |
| `GOOGLE_CLIENT_ID/SECRET`, `GITHUB_CLIENT_ID/SECRET` | Enable "Sign in with …" (blank = provider disabled). |
| `THROTTLE_ANON`, `THROTTLE_USER`, `THROTTLE_AUTH`, `THROTTLE_NUM_PROXIES` | Rate limits; set the proxy count when behind a reverse proxy. |
| `PASSWORD_MIN_LENGTH`, `PASSWORD_RESET_TIMEOUT`, `EMAIL_VERIFICATION_MAX_AGE` | Password / token policy. |
| `INSTALL_DEV`, `GUNICORN_*`, `WEB_PORT`, `DB_HOST_PORT`, `REDIS_HOST_PORT` | Container build/run knobs. |

`.env` is git-ignored; commit only `.env.example`.

## Running the tests

```bash
docker compose run --rm web pytest          # against the compose PostgreSQL (recommended)
```

The suite (`config/settings_test.py`) swaps Redis for in-memory caches, sends mail to an in-memory outbox and runs
Celery tasks eagerly, so only PostgreSQL is needed. Without Docker you can run it on SQLite:

```bash
pip install -r requirements-dev.txt
DATABASE_ENGINE=sqlite pytest
```

About 460 tests, ~99% line coverage. Add `--cov=apps --cov=config --cov-report=term-missing` for a coverage report.
They cover:

* **Auth**: signup/login/logout, profile, password change & reset, email verification, OAuth account linking and provider
  exchange (with the pre-hijacking defence), inactive/deleted users, token expiry and tampering.
* **Security**: CSRF, CORS preflight, an endpoint-by-caller permission matrix (anonymous / user / admin), separate admin
  session, throttling, ownership isolation, NUL-character and oversized-payload rejection.
* **Data**: projects, folders, tags, templates, import/export, publishing and moderation, gallery search/filter/sort,
  likes, comments, follows, remixes, cascade deletes, query-count guards against N+1.
* **Infrastructure**: settings parsing in a fresh process, error format, health check, Celery task registration and retry
  policy, email content, admin bootstrap and gallery seeding commands.

## Continuous integration

`.github/workflows/ci.yml` runs on every push to `master`/`main` and on every pull request (a newer push cancels the
run still in progress):

| Job | What it checks |
| --- | --- |
| **Lint** | `ruff check .` (unused code, undefined names, likely bugs; config in `ruff.toml`). |
| **Tests (PostgreSQL)** | The full suite against a real PostgreSQL 16 service, with a coverage gate (`--cov-fail-under=95`) and the coverage % in the run summary. |
| **Django checks** | `manage.py check`, no model change without a migration (`makemigrations --check`), and the production `check --deploy` passing with a production-shaped config. |
| **Docker image and Compose files** | Builds the production image, asserts it runs as non-root, has no test tooling and no `.env` files, and validates both Compose files (with and without the Caddy profile) and the Caddyfile. |

Run the same checks locally: `ruff check .`, `docker compose run --rm web pytest --cov=apps --cov=config`.
Dependabot (`.github/dependabot.yml`) opens weekly PRs for Python, Docker and GitHub Actions updates.
To gate merges, enable branch protection on `master` and require the four jobs above.

## Project layout

```
config/            settings (env driven), urls, celery app, test settings
apps/
  core/            error format, health check, session/celery helpers
  accounts/        User model, auth + OAuth endpoints, tokens, emails (Celery tasks)
  projects/        Project & Folder models, starter templates (data/templates.json)
  community/       gallery, likes, comments, follows, `seed_gallery` command
  moderation/      admin sign-in and circuit review
scripts/start-web.sh   container entrypoint (migrate, collectstatic, admin, seeds, gunicorn)
```

## API overview

Base path `/api/v1/`. JSON in, JSON out, trailing slashes required.

### Conventions

* **Auth**: Django session cookie stored in Redis. State-changing requests from a signed-in user must send the
  `X-CSRFToken` header; fetch a token with `GET /auth/csrf/` (it also sets the `csrftoken` cookie). Call the API with
  `credentials: 'include'`.
* **Anonymous → `401`** (not 403) on endpoints that need a login.
* **Errors** always look like `{"detail": "<message safe to show>", "code": "<slug>"}`; validation errors add
  `"errors": {field: [messages]}`. Throttled requests return `429` with `retryAfter` seconds.
* **Shapes** mirror the frontend's mock data layer: camelCase keys (`createdAt`, `ownerId`, `likeCount`, …) and
  timestamps as **epoch milliseconds**. Ids are UUID strings.

### Auth (`/auth/…`)

| Method & path | Notes |
| --- | --- |
| `GET csrf/` | `{csrfToken}` |
| `POST signup/` `{name,email,password}` | Creates the account, a starter circuit, signs in, queues the verification email. |
| `POST login/` `{email,password}` · `POST logout/` | |
| `GET/PATCH/DELETE me/` | PATCH accepts `name`, `avatar`. DELETE removes the account and its data. |
| `POST password/change/` `{current,next}` | Other sessions are signed out. Accounts created via OAuth may omit `current`. |
| `POST password/forgot/` `{email}` | Always `202` (no account probing). Emails a reset link. |
| `POST password/reset/` `{token,password}` | Tokens are single-use and expire (`PASSWORD_RESET_TIMEOUT`). |
| `POST verify-email/` `{token}` · `POST verify-email/resend/` | Links in mails point to `FRONTEND_URL/verify-email?token=…` and `FRONTEND_URL/reset-password?token=…`. |
| `GET oauth/providers/` · `POST oauth/<google\|github>/` `{code,redirectUri}` | Server-side code exchange; the client secret never reaches the browser. |

### Projects & folders (sign-in required, owner only)

| Method & path | Notes |
| --- | --- |
| `GET/POST projects/` | POST body: optional `name`, `template` (`blank`, `blink`, `traffic`, `parking`, `rgbled`, `servoseg`, `relaymotor`, `sensors`), `parts`, `wires`, `code`, `folder`. |
| `GET/PATCH/DELETE projects/<id>/` | PATCH accepts `name`, `description`, `tags`, `folder`, `parts`, `wires`, `code` (autosave). |
| `POST projects/<id>/duplicate/` · `publish/` `{description,tags}` · `unpublish/` | Publishing only *submits* for review. |
| `GET projects/<id>/export/` · `POST projects/import/` `{name,parts,wires,code}` | |
| `GET/POST folders/` · `PATCH/DELETE folders/<id>/` | Deleting a folder keeps its projects. |

### Community (anonymous reads, sign-in for actions)

| Method & path | Notes |
| --- | --- |
| `GET gallery/?q=&tag=&author=&sort=popular\|new` | `tag=__following__` = authors you follow. Items include `likeCount` and `liked`. |
| `GET gallery/<id>/` | |
| `PUT/DELETE gallery/<id>/like/` | Idempotent; returns `{liked, likeCount}`. |
| `GET/POST gallery/<id>/comments/` · `DELETE gallery/<id>/comments/<cid>/` | Only your own comments can be deleted. |
| `POST gallery/<id>/remix/` | Copies the circuit into your projects. |
| `GET following/` · `PUT/DELETE following/<handle>/` | Idempotent follow / unfollow. |

### Moderation (`/admin/…`, separate admin session)

`POST admin/login/` `{email,password}` (staff accounts only; no signup), `POST admin/logout/`,
`GET admin/session/`, `GET admin/circuits/pending/`, `POST admin/circuits/<id>/approve/`, `POST admin/circuits/<id>/reject/`.
The admin sign-in is stored under its own session key, so signing a regular user in or out doesn't affect it.

## Wiring up the frontend

`src/lib/api.js` in the frontend is the seam. Points to be aware of when replacing the localStorage mock with
`fetch` calls:

* Calls become **async**; the slices currently call `api.*` synchronously and their initial state reads `api.me()` /
  `api.projects()` directly, so they need to load data on start-up (e.g. `GET /auth/me/`, treat `401` as "signed out").
* Mock token hand-off is gone: the verification / reset tokens arrive by email, not as return values.
* `toggleLike` / `toggleFollow` become explicit `PUT` / `DELETE` calls (the response tells you the new state).
* Seed circuits and template projects now come from the server; template documents are ported from `lib/templates.js`
  into `apps/projects/data/templates.json` (regenerate it if the frontend templates change).
* The frontend's mock OAuth becomes the real redirect flow: send the user to the provider, then `POST` the returned
  `code` and the `redirectUri` you used.

## Behaviour worth knowing

* **Moderation**: a published circuit only appears in the gallery once an admin approves it. Edits the owner makes to an
  already-approved circuit go live without a fresh review (same as the mock); re-publishing does require review again.
* **Handles** (`name_ab12`) are generated once at signup and never change, so follows and links survive renames.
* **OAuth**: identities are only trusted when the provider reports a verified email. Signing in with a provider whose
  email matches an *unverified* local account verifies it and removes that account's password (prevents
  pre-registration hijacking).
* **Passwords** need 8+ characters (configurable), not all digits, not a common password. The frontend mock only
  required 4, so its signup validation/`PasswordStrength` hints should be aligned.
* Lists are not paginated (the frontend expects plain arrays); add pagination if galleries grow large.

## Deploying on Render

`render.yaml` is a Render Blueprint that creates everything: the API (Docker web service), the Celery worker,
managed PostgreSQL 16 and a Key Value (Redis-compatible) instance, all in one region (Singapore by default) so they
talk over Render's private network. Plans in the file are paid instances: background workers can't be free, free Postgres
expires after 30 days and free Key Value doesn't persist sessions or queued jobs. Adjust plans/region to taste.

**1. Edit `render.yaml`** so the domains match yours (`FRONTEND_URL`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`,
`DJANGO_ALLOWED_HOSTS`, and `domains:` under the web service).

**2. Create it**: push the repo to GitHub, then Render dashboard -> **New -> Blueprint** -> select the repo. Render
prompts for every `sync: false` value:

| Service | Variable | Value |
| --- | --- | --- |
| web | `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Moderator login. Password must be 12+ characters and not a known default. |
| web | `DJANGO_ADMIN_URL` | Unguessable path for Django's admin, e.g. `ops-7f3k9x` (no slashes). |
| web | `GOOGLE_*`, `GITHUB_*` | OAuth credentials (see below). Not using a provider? Remove its two lines from `render.yaml`. |
| worker | `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | Brevo SMTP login and SMTP key. |

`DJANGO_SECRET_KEY` is generated once by Render and shared through the `techomato-shared` group, so the web service and
worker sign and verify email tokens with the same key. `DATABASE_URL` and `REDIS_URL` are wired in automatically.

**3. How a deploy runs**: Render builds the Dockerfile, runs `sh scripts/predeploy.sh` on a separate instance (deployment
checks, migrations, admin bootstrap, gallery seeds), then starts the new web instance and switches traffic once
`/api/v1/health/` is healthy. The web container skips release tasks (`RUN_RELEASE_TASKS=false`), so scaling to several
instances never runs migrations concurrently. The container also refuses to start if the deployment checks find
unsafe config (see the production section below).

**4. Custom domain**: in the web service's Settings add `api.techomato.com` and create the CNAME record Render shows
(`api` -> `techomato-api-xxxx.onrender.com`); Render issues the TLS certificate. The `*.onrender.com` hostname keeps
working (it is added to `ALLOWED_HOSTS` automatically).

**5. Cookies and domains**: the SPA and the API must be on the **same site** (`techomato.com` and `api.techomato.com`)
for the default `SameSite=Lax` cookies to work. If the SPA is on another registrable domain (for example a `*.vercel.app`
preview) browsers won't send the login cookie cross-site: set `SESSION_COOKIE_SAMESITE` and `CSRF_COOKIE_SAMESITE`
to `None` (they are already Secure) or, better, serve the SPA from your own domain. Point the frontend at the API with
`VITE_API_BASE_URL=https://api.techomato.com/api/v1`.

**6. Email (Brevo)**: Brevo only accepts SMTP logins from allowed IPs. Either turn the restriction off
(Brevo -> Security -> Authorised IPs) or add your Render outbound IP ranges (service -> **Connect** -> Outbound),
otherwise sends fail with `525 5.7.1 Unauthorized IP address`. Also authenticate `techomato.com` (SPF/DKIM) in Brevo.

**7. OAuth**: register `https://techomato.com/oauth/callback/google` (Google Cloud Console) and
`https://techomato.com/oauth/callback/github` (a separate GitHub OAuth App for production).

**8. Verify the rate-limit client IP** (one-time, important): Render's proxy chain decides which `X-Forwarded-For` entry is
the real client. Open `https://api.techomato.com/api/v1/health/?debug=ip` from your own machine and compare
`client.ident` with your public IP (search "what is my IP"). If it matches, `THROTTLE_NUM_PROXIES=1` is right. If it
shows a Render/Cloudflare address instead, every visitor would share one login rate-limit bucket: raise
`THROTTLE_NUM_PROXIES` (2, 3...) in the `techomato-shared` group until `ident` is your IP. The endpoint only echoes
the caller's own request details.

**Notes**
* Cache, sessions and the Celery broker share Key Value's database 0 (separate key prefixes). Never call
  `cache.clear()` in production code: on Redis it flushes the whole database, sessions included.
* The `noeviction` policy protects sessions and queued jobs; if memory fills up writes fail loudly instead of
  silently dropping users' sessions. Upgrade the Key Value plan if you approach the limit.
* The web service listens on Render's `PORT` (10000). Health checks reach it without a valid `Host` header
  (`HealthCheckMiddleware`); every other route still enforces `ALLOWED_HOSTS`.
* Logs: Render dashboard -> service -> Logs. Postgres backups are a paid-plan feature; schedule your own `pg_dump` if
  you need more than Render provides.

## Deploying with Docker on your own server

`docker-compose.prod.yml` is a hardened stack: no source bind-mounts, PostgreSQL and Redis on the internal network only
(Redis is password protected), non-root containers with dropped capabilities, restart policies, healthchecks, gunicorn
worker recycling, and an optional Caddy reverse proxy that obtains HTTPS certificates automatically.

```bash
cp .env.production.example .env.production      # then fill in every empty/CHANGE value
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
# with automatic HTTPS (Caddy on ports 80/443, DNS for API_DOMAIN must already point at this host):
docker compose -f docker-compose.prod.yml --env-file .env.production --profile proxy up -d --build
```

* **It refuses to boot with unsafe config.** When `DJANGO_DEBUG` is off the container runs
  `manage.py check --deploy --fail-level ERROR` before migrating. It fails on: debug on, a short/placeholder
  `DJANGO_SECRET_KEY`, a weak/default `ADMIN_PASSWORD` or `POSTGRES_PASSWORD`, non-HTTPS `FRONTEND_URL`/CORS/CSRF origins,
  non-Secure cookies, and `ALLOWED_HOSTS` of `*` or only localhost. Warnings (no real email backend, HSTS off, no proxy
  count) are printed but don't stop the boot. Run the same check yourself: `python manage.py check --deploy`.
* **Secrets**: keep `.env.production` out of git (already ignored) and out of the image (`.dockerignore`). Prefer your host's
  secret store where available.
* **Domains**: the API host goes in `DJANGO_ALLOWED_HOSTS`/`API_DOMAIN`; the SPA origin in `FRONTEND_URL`,
  `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS`. Same registrable domain (`techomato.com` + `api.techomato.com`) works
  with `SameSite=Lax`; different domains need `SameSite=None` (cookies must then be Secure).
* **OAuth**: register `https://techomato.com/oauth/callback/google` and `/github` as redirect URIs (GitHub needs a separate
  OAuth App per environment) and put the credentials in `.env.production`.
* **Django admin** is served at `DJANGO_ADMIN_URL` (default `django-admin/`; pick something unguessable).
* **Behind your own proxy/load balancer** instead of Caddy: keep `WEB_BIND=127.0.0.1`, forward `X-Forwarded-Proto` and
  `X-Forwarded-For`, and set `USE_X_FORWARDED_PROTO=true` and `THROTTLE_NUM_PROXIES` to the number of proxies.
* **Operations**
  * Logs: `docker compose -f docker-compose.prod.yml logs -f web worker`.
  * Update: `git pull && docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build`
    (migrations run automatically on start).
  * Scale workers: `... up -d --scale worker=3`.
  * Backup: `docker compose -f docker-compose.prod.yml exec -T db pg_dump -U techomato techomato > backup.sql` (schedule
    this and copy it off the host). Redis holds sessions/cache/queue only and persists via AOF; flushing it signs everyone out.
  * The `db` and `redis` data live in the `pgdata` / `redisdata` volumes: don't run `down -v` in production.

### Known limits

* On the plain Docker stack one `web` container runs migrations at start-up; to scale `web` horizontally set `RUN_RELEASE_TASKS=false` and run `sh scripts/predeploy.sh` once per release (Render does this for you).
* Edits to an already-approved circuit go live without a new review (re-publishing does require one).
* Lists are not paginated (the frontend expects plain arrays).
