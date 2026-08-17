FROM python:3.12-slim

WORKDIR /

# Копируем только requirements — Docker кэширует этот слой
COPY tests/requirements.txt /tests/requirements.txt
COPY admin_panel/requirements.txt /admin_panel/requirements.txt

# Устанавливаем зависимости один раз (кэшируется Docker-слоем)
RUN pip install --no-cache-dir -r /tests/requirements.txt -r /admin_panel/requirements.txt

CMD ["pytest", "/tests", "-v"]
