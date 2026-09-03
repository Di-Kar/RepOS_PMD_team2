# Репозиторий проекта PMD

Онлайн-кинотеатр: панель администратора, ETL и полнотекстовый поиск.

## Структура репозитория

- `admin_panel` — панель администратора на Django (модели фильмов, API, поиск, конфигурация nginx в `admin_panel/nginx`, спецификация API в `admin_panel/docs/openapi.yaml`).
- `database` — скрипты для наполнения базы данных (структура формируется миграциями django из admin_panel).
- `fulltext_search` — сервис для полнотекстового поиска (ETL переноса данных из PostgreSQL в Elasticsearch).
- `async_api` — асинхронное API для онлайн-кинотеатра.
- `auth_service` — сервис авторизации (JWT, роли/RBAC; свои PostgreSQL и Redis, все env-переменные с префиксом `AUTH_`).
- `event_api` — приём пользовательских событий (клики, просмотры страниц, кастомные события) и публикация их в Kafka; контракт событий — `docs/user_events_contract.md`, env-переменные с префиксом `EVENTS_`.
- `analytics_etl` — ETL, вычитывающий события из Kafka и загружающий их в ClickHouse (схема БД — `clickhouse_init/init.sql`), env-переменные с префиксом `ANALYTICS_`.
- `shared` — общий код, используемый несколькими сервисами (сейчас — схемы событий `shared/event_schemas.py`, единая точка валидации для `event_api` и `analytics_etl`).
- `ugc_service` — сервис пользовательского контента: закладки, лайки и рецензии к фильмам; хранилище — шардированный кластер MongoDB (конфиг — `docker/setup_mongo_cluster.sh`), авторизация — JWT от `auth_service` (`ugc_service` его не выпускает, а проксирует `/api/v1/auth/login`).
- `tests` — все тесты проекта, образ собирается из `tests/Dockerfile` с кэшированием зависимостей.

## Запуск проекта (без тестов и с тестами)

```bash
cp .env.example .env  # заполнить значения (но проще взять готовый в чате команды и подложить)
docker compose up -d --build
-----------------------------
docker compose up -d --build; if ($?) { docker compose run --rm tests }
```

## Остановка и очистка всего проекта (включая тесты)

```bash
docker compose --profile tests down -v --remove-orphans
```

После запуска доступны следующие эндпоинты:
- admin_panel:
  - Панель администратора (http://localhost/admin)
  - API (http://localhost/api/v1)
  - Swagger (http://localhost:8080)
  - Тестирование полнотекстового поиска (http://localhost/search)
- Elasticsearch: http://localhost:9200
- async_api:
  - Swagger (http://localhost:8000/docs)
- auth_service:
  - Swagger (http://localhost:8001/docs)
- event_api:
  - Swagger (http://localhost:8002/docs)
- ugc_service:
  - Swagger (http://localhost:8003/docs)
- jaeger: http://localhost:16686
- kafka-ui: http://localhost:8090

Миграции БД авторизации применяются автоматически (one-shot сервис `auth_migrations`).

## Тесты

Все тесты живут в папке `tests/` (подпапка = тестируемый сервис: `admin_panel`, `async_api`, `auth_service`, `event_api`, `analytics_etl`, `shared`, `ugc_service`) и запускаются одним контейнером. Нужен запущенный проект:

### Запуск всех тестов

```bash
# Первый запуск — собрать образ с зависимостями (зависимости кэшируются в слое Docker):
docker compose build tests

# Запуск всех тестов (локальные файлы примонтированы через volumes, пересборка не нужна):
docker compose run --rm tests
```

### Запуск тестов только одного типа (например analytics ETL-тестов)

```bash
docker compose run --rm tests pytest /tests/analytics_etl -v
```

Сервис `tests` вынесен в отдельный compose-профиль и при `docker compose up` не стартует — только явно, командой выше.

⚠️ Тесты меняют данные работающего стека: пересоздают индексы Elasticsearch (movies/genres/persons), очищают Redis-кэш и регистрируют тестовых пользователей в auth-базе. Не запускать на данных, которые жалко; данные ES восстановит ETL в течение цикла синхронизации.

Создание суперпользователя auth_service:

```bash
docker compose run --rm auth_service python -m src.cli create-superuser admin@example.com -p 'Admin12345'
```

## Разработка

Требуется Python 3.12.

Установка зависимостей разработчика (для `.venv`, линтинга и работы с кодом сервисов локально):

```bash
pip install -r requirements.txt
```

Запуск линтера:

```bash
ruff check . --fix
```

## OAuth Google

https://console.cloud.google.com/apis/credentials?project=repospmd-80560

Нужны реальные креды из Google Cloud Console:

1. Зайти в Google Cloud Console (https://console.cloud.google.com/) → создать проект (если ещё нет) → APIs & Services → Credentials → Create Credentials → OAuth client ID → тип Web application.
2. В Authorized redirect URIs прописать ровно:
http://localhost:8001/api/v1/auth/oauth/google/callback
3. Также потребуется настроить OAuth consent screen (если ещё не настроен) — тип External, добавить свой zentkhv27@gmail.com в Test users (пока приложение не опубликовано, войти смогут только явно добавленные тестовые аккаунты).
4. Скопировать выданные Client ID и Client Secret в .env:
GOOGLE_CLIENT_ID=<из консоли>
GOOGLE_CLIENT_SECRET=<из консоли>
5. В разделе Authorized redirect URIs добавь: http://localhost:8001/api/v1/auth/oauth/google/callback

Для того, чтобы привязать аккаунт нужно пройти по ссылке и выполнить все шаги, в результате получите токены:
http://localhost:8001/api/v1/auth/oauth/google/login