# Репозиторий проекта PMD

Онлайн-кинотеатр: панель администратора, ETL и полнотекстовый поиск.

## Структура репозитория

- `admin_panel` — панель администратора на Django (модели фильмов, API, поиск, конфигурация nginx в `admin_panel/nginx`, спецификация API в `admin_panel/docs/openapi.yaml`).
- `database` — скрипты для наполнения базы данных (структура формируется миграциями django из admin_panel).
- `fulltext_search` — сервис для полнотекстового поиска (ETL переноса данных из PostgreSQL в Elasticsearch).
- `async_api` — асинхронное API для онлайн-кинотеатра.

## Запуск основной части проекта

```bash
cp .env.example .env  # заполнить значения (но проще взять готовый в чате команды и подложить)
docker compose up -d --build
docker compose down -v
```

После запуска доступны следующие эндпоинты:
- admin_panel:
  - Панель администратора (http://localhost/admin)
  - API (http://localhost/api/v1)
  - Swagger (http://localhost:8080)
  - Тестирование полнотекстового поиска (http://localhost/search)
- Elasticsearch: http://localhost:9200
- async_api:
  - Swagger (http://localhost:8000/api/openapi)
  - OpenAPI-схема (http://localhost:8000/api/openapi.json)

## Запуск части из 6 спринта 

```bash
docker compose -f docker-compose-auth-service-test.yml up -d --build postgres redis
docker compose -f docker-compose-auth-service-test.yml run --build --rm migrations
docker compose -f docker-compose-auth-service-test.yml up -d --build auth_service

docker compose -f docker-compose-auth-service-test.yml down -v
```

После запуска доступны следующие эндпоинты:
- auth_api:
  - Swagger (http://localhost:8001/docs)

## Разработка

Требуется Python 3.12.

Установка зависимостей разработчика (для `.venv`, линтинга и работы с кодом сервисов локально):

```bash
pip install -r requirements.txt
```