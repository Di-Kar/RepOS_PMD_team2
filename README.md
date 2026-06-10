# Репозиторий проекта PMD

Онлайн-кинотеатр: панель администратора, ETL и полнотекстовый поиск.

## Структура репозитория

- `admin_panel/` — панель администратора на Django (модели фильмов, API, поиск, конфигурация nginx в `admin_panel/nginx/`, спецификация API в `admin_panel/docs/openapi.yaml`).
- `async_api/` — асинхронное API для онлайн-кинотеатра.
- `fulltext_search/` — сервис полнотекстового поиска и ETL переноса данных из PostgreSQL в Elasticsearch (`etl/` — python-скрипты ETL, `docs/` — задание и схема индекса).
- `docker-compose.yml` — единый docker-compose для всех сервисов.
- `.env` / `.env.example` — единый файл переменных окружения для всех сервисов.

## Запуск

```bash
cp .env.example .env  # заполнить значения
docker compose up -d --build
docker compose down -v
```

После запуска:

- Панель администратора и API: http://localhost/admin, http://localhost/api/
- Elasticsearch: http://localhost:9200
- Swagger UI: http://localhost:8080
