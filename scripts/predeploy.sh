#!/bin/sh
# One-off release step: run before the new web instances start (Render's
# preDeployCommand, or manually before scaling web horizontally).
set -eu

echo "==> Deployment checks"
python manage.py check --deploy --fail-level ERROR

echo "==> Applying database migrations"
python manage.py migrate --noinput

echo "==> Ensuring admin account"
python manage.py ensure_admin

if [ "${SEED_GALLERY:-true}" = "true" ]; then
  echo "==> Seeding community gallery"
  python manage.py seed_gallery
fi
