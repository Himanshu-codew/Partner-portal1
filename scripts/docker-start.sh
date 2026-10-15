#!/usr/bin/env sh
# Container start command (Dockerfile CMD). Mirrors build.sh for the steps
# that need the database, then starts gunicorn on Render's $PORT.
set -e

python manage.py migrate --no-input

# Create superuser if env variables are provided
if [ -n "${DJANGO_SUPERUSER_USERNAME}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD}" ] && [ -n "${DJANGO_SUPERUSER_EMAIL}" ]; then
  python manage.py createsuperuser --noinput || true
fi

# One worker by default (512 MB on the free plan); WEB_CONCURRENCY overrides.
# GUNICORN_TIMEOUT: raise it on the OCR helper, where one request runs OCR
# on a whole multi-page PDF.
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-10000}" \
  --workers "${WEB_CONCURRENCY:-1}" \
  --timeout "${GUNICORN_TIMEOUT:-120}"
