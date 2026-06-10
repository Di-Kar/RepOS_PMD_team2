#!/usr/bin/env bash

set -e

python manage.py migrate --no-input
python manage.py collectstatic --no-input

if [ -n "$DJANGO_SUPERUSER_USERNAME" ]; then
    python manage.py createsuperuser --no-input 2>&1 | grep -v 'already taken' || true
fi

uwsgi --strict --ini /opt/app/uwsgi/uwsgi.ini
