FROM python:3.12-slim

WORKDIR /opt/app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

COPY requirements.txt ./
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove gcc \
    && rm -rf /var/lib/apt/lists/*

# Alembic конфигурация/скрипты миграций
COPY alembic.ini ./
COPY alembic ./alembic

COPY src/ ./
#RUN chmod +x ./src/main.py

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
