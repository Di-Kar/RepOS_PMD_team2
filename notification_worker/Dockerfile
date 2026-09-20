FROM python:3.12-slim

WORKDIR /opt/app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

# Нет HTTP-порта — оба процесса (render/email_sender) только consumer-loop.
# Конкретная точка входа задаётся `command:` в docker-compose.yml:
#   ["python", "-m", "src.main_render"]
#   ["python", "-m", "src.main_send_email"]
#   ["python", "scripts/migrate.py"]
CMD ["python", "-m", "src.main_render"]
