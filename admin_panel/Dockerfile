FROM python:3.10-slim

WORKDIR /opt/app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UWSGI_PROCESSES=1 \
    UWSGI_THREADS=16 \
    UWSGI_HARAKIRI=240 \
    DJANGO_SETTINGS_MODULE=config.settings

COPY requirements.txt requirements-prod.txt ./

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc-dev \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-prod.txt \
    && apt-get purge -y --auto-remove gcc \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN sed -i 's/\r//' run_uwsgi.sh \
    && chmod +x run_uwsgi.sh \
    && mkdir -p /opt/app/static \
    && useradd --system --uid 1000 app \
    && chown -R app:app /opt/app

USER app

EXPOSE 8000

ENTRYPOINT ["/opt/app/run_uwsgi.sh"]
