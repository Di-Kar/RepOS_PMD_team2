#!/bin/bash
set -e  # Выход при любой ошибке
python manage.py migrate --noinput

python manage.py collectstatic --noinput --clear

python manage.py shell << EOF
from django.contrib.auth import get_user_model
User = get_user_model()

username = '${SUPERUSER_USERNAME}'
email = '${SUPERUSER_EMAIL:-}'
password = '${SUPERUSER_PASSWORD}'

if username and password:
    if not User.objects.filter(username=username).exists():
        User.objects.create_superuser(username=username, email=email, password=password)
        print(f"Superuser '{username}' created")
    else:
        print(f"Superuser '{username}' already exists")
else:
    print("Superuser env vars not set, skipping creation")
EOF

exec "$@"
