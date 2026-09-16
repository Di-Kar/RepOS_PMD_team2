FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=notification_admin.settings

WORKDIR /opt/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# ИЗМЕНЕННАЯ СТРОКА: увеличен таймаут и добавлено надежное зеркало
RUN pip install --no-cache-dir --default-timeout=100 --index-url https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY . .

# Явный запуск сервера (чтобы избежать ошибки "задача не задает команду")
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]