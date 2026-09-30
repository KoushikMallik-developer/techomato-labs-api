#!/bin/sh
# Boots the API container: deployment checks, (optionally) release tasks, collect
# static files, then hand over to gunicorn.
set -eu

if [ "${DJANGO_DEBUG:-false}" != "true" ]; then
  echo "==> Running deployment checks (refusing to start on errors)"
  python manage.py check --deploy --fail-level ERROR
fi

# Migrations, admin bootstrap and seeds run here by default. Platforms with a
# separate release step (Render preDeployCommand -> scripts/predeploy.sh) set
# RUN_RELEASE_TASKS=false so several web instances never migrate concurrently.
if [ "${RUN_RELEASE_TASKS:-true}" = "true" ]; then
  echo "==> Applying database migrations"
  python manage.py migrate --noinput

  echo "==> Ensuring admin account"
  python manage.py ensure_admin

  if [ "${SEED_GALLERY:-true}" = "true" ]; then
    echo "==> Seeding community gallery"
    python manage.py seed_gallery
  fi
fi

echo "==> Collecting static files"
python manage.py collectstatic --noinput --verbosity 0

RELOAD=""
if [ "${GUNICORN_RELOAD:-false}" = "true" ]; then
  RELOAD="--reload"
fi

echo "==> Starting gunicorn"
# shellcheck disable=SC2086
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${GUNICORN_WORKERS:-3}" \
  --timeout "${GUNICORN_TIMEOUT:-30}" \
  --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-30}" \
  --max-requests "${GUNICORN_MAX_REQUESTS:-2000}" \
  --max-requests-jitter "${GUNICORN_MAX_REQUESTS_JITTER:-200}" \
  --worker-tmp-dir /dev/shm \
  --access-logfile - \
  --error-logfile - \
  $RELOAD
