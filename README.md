# Репозиторий проекта PMD

Онлайн-кинотеатр: панель администратора, ETL и полнотекстовый поиск.

## Структура репозитория

- `admin_panel` — панель администратора на Django (модели фильмов, API, поиск, конфигурация nginx в `admin_panel/nginx`, спецификация API в `admin_panel/docs/openapi.yaml`).
- `database` — скрипты для наполнения базы данных (структура формируется миграциями django из admin_panel).
- `fulltext_search` — сервис для полнотекстового поиска (ETL переноса данных из PostgreSQL в Elasticsearch).
- `async_api` — асинхронное API для онлайн-кинотеатра.
- `auth_service` — сервис авторизации (JWT, роли/RBAC; свои PostgreSQL и Redis, все env-переменные с префиксом `AUTH_`).
- `tests` — все тесты проекта (HTTP-тесты async_api и auth_service, один общий контейнер).

## Запуск проекта (без тестов)

```bash
cp .env.example .env  # заполнить значения (но проще взять готовый в чате команды и подложить)
docker compose up -d --build
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
- jaeger: http://localhost:16686

Миграции БД авторизации применяются автоматически (one-shot сервис `auth_migrations`).

## Тесты

Все тесты живут в папке `tests/` (HTTP-тесты, подпапка = тестируемый сервис: `async_api`, `auth_service`) и запускаются одним контейнером. Нужен запущенный проект:

```bash
docker compose run --rm tests
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