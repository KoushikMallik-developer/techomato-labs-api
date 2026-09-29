# Techomato Labs API

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

It covers auth flows (signup/login/logout, password change & reset, email verification, OAuth account
linking and provider exchange), CSRF and throttling, project/folder CRUD and ownership isolation, publishing and
moderation, gallery search/filter/sort, likes, comments, follows, remixes, seeding and the admin bootstrap command.

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
| `POST verify-email/` `{token}` · `POST verify-email/resend/` | Links in mails point to `FRONTEND_URL/#/verify-email?token=…` and `/#/reset-password?token=…`. |
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

## Production notes

* Build with `INSTALL_DEV=false`, set `DJANGO_DEBUG=false`, a real `DJANGO_SECRET_KEY`, strong DB/admin passwords, HTTPS
  cookie flags, `USE_X_FORWARDED_PROTO=true` behind a TLS proxy, and `THROTTLE_NUM_PROXIES` to match your proxy chain.
* Point `EMAIL_BACKEND` at SMTP, and remove the source bind mounts from `docker-compose.yml`.
* Run more workers with `docker compose up --scale worker=N`. Redis persists to the `redisdata` volume (AOF), so
  sessions survive restarts; flushing Redis signs everyone out.
