#!/bin/sh
# Boots the API container: migrate, collect static files, bootstrap admin +
# gallery seeds, then hand over to gunicorn.
set -eu

echo "==> Applying database migrations"
python manage.py migrate --noinput

echo "==> Collecting static files"
python manage.py collectstatic --noinput --verbosity 0

echo "==> Ensuring admin account"
python manage.py ensure_admin

if [ "${SEED_GALLERY:-true}" = "true" ]; then
  echo "==> Seeding community gallery"
  python manage.py seed_gallery
fi

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
  --access-logfile - \
  $RELOAD
