#!/usr/bin/env bash

set -e

python manage.py migrate --no-input
python manage.py collectstatic --no-input

# Username = email (та же учётка, что бутстрапится в auth_service).
# get_or_create + set_password вместо createsuperuser --no-input: тот не
# обновляет пароль существующего пользователя. Best-effort — не блокирует старт.
if [ -n "$DJANGO_SUPERUSER_EMAIL" ]; then
    set +e
    python manage.py shell -c "
import os
from django.contrib.auth import get_user_model

User = get_user_model()
email = os.environ['DJANGO_SUPERUSER_EMAIL']
password = os.environ['DJANGO_SUPERUSER_PASSWORD']

User.objects.filter(username='admin').exclude(username=email).delete()

user, _ = User.objects.get_or_create(username=email, defaults={'email': email})
user.email = email
user.is_staff = True
user.is_superuser = True
user.is_active = True
user.set_password(password)
user.save()
print(f'Bootstrap admin {email} ensured (password synced with .env)')
" || echo "WARNING: bootstrap admin sync failed, continuing anyway"
    set -e
fi

uwsgi --strict --ini /opt/app/uwsgi/uwsgi.ini
