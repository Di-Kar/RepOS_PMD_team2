# Репозиторий проекта PMD

Онлайн-кинотеатр: панель администратора, ETL и полнотекстовый поиск.

## Структура репозитория

- `admin_panel` — панель администратора на Django (модели фильмов, API, поиск, конфигурация nginx в `admin_panel/nginx`, спецификация API в `admin_panel/docs/openapi.yaml`).
- `database` — скрипты для наполнения базы данных (структура формируется миграциями django из admin_panel).
- `fulltext_search` — сервис для полнотекстового поиска (ETL переноса данных из PostgreSQL в Elasticsearch).
- `async_api` — асинхронное API для онлайн-кинотеатра.
- `auth_service` — сервис авторизации (JWT, роли/RBAC; свои PostgreSQL и Redis, все env-переменные с префиксом `AUTH_`); при регистрации и смене пароля best-effort отправляет уведомление через `notification_api` (S10_T7, issue #100).
- `event_api` — приём пользовательских событий (клики, просмотры страниц, кастомные события) и публикация их в Kafka; контракт событий — `docs/user_events_contract.md`, env-переменные с префиксом `EVENTS_`.
- `analytics_etl` — ETL, вычитывающий события из Kafka и загружающий их в ClickHouse (схема БД — `clickhouse_init/init.sql`), env-переменные с префиксом `ANALYTICS_`.
- `shared` — общий код, используемый несколькими сервисами: схемы событий `shared/event_schemas.py` (`event_api`/`analytics_etl`) и схемы заявок на уведомления `shared/notification_schemas.py` (`notification_api`/`notification_worker`).
- `ugc_service` — сервис пользовательского контента: закладки, лайки и рецензии к фильмам; хранилище — шардированный кластер MongoDB (конфиг — `docker/setup_mongo_cluster.sh`), авторизация — JWT от `auth_service` (`ugc_service` его не выпускает, а проксирует `/api/v1/auth/login`).
- `notification_api` — приём заявок на создание уведомлений (от `admin_panel`, `auth_service` и других сервисов), фан-аут по получателям и публикация в Kafka. Каналы `email`/`sms`/`push` сам не рендерит и не отправляет — доставка этим занимается `notification_worker`; канал `websocket` (S10_T4, issue #97) — исключение, доставляется им же самим (см. §10 контракта). Контракт — `docs/notification_requests_contract.md`, env-переменные с префиксом `NOTIFICATIONS_`.
- `notification_worker` (S10_T3, issue #96) — два процесса из одного образа: `notification_worker_render` (читает `notifications.requests.v1`, обогащает профилем из `auth_service` internal-эндпоинта, рендерит шаблон, публикует в `notifications.ready.v1`) и `notification_worker_email_sender` (читает `notifications.ready.v1`, идемпотентно отправляет email через SMTP, обновляет статусы в `notification_log`/`notifications`/`notification_history`). Env-переменные с префиксом `NOTIFICATION_WORKER_`.
- `notification_admin_panel` — панель администратора на Django для создания и отправки уведомлений (обращается к `notification_api`); своя PostgreSQL (`notification_postgres`, общая физическая БД с `notification_api`/`notification_worker`) и cron-воркер для отложенных/повторяющихся рассылок (`notification_admin_cron`).
- `link_shortener_service` — универсальный сервис коротких ссылок: `POST /api/v1/links` создаёт короткую ссылку (S2S, `X-API-Key`), `GET /r/{code}` резолвит её по клику (302 на действительный код, 404 на несуществующий/просроченный). Первый потребитель — `auth_service`: ссылка подтверждения email в welcome-письме при регистрации, при переходе проставляет `email_confirmed=true` через internal-эндпоинт `auth_service` и редиректит на настраиваемый `redirectUrl` (по умолчанию — главная страница). Своя PostgreSQL (`link_shortener_postgres`), env-переменные с префиксом `LINKS_`. Контракт — `docs/link_shortener_contract.md`.
- `tests` — все тесты проекта, образ собирается из `tests/Dockerfile` с кэшированием зависимостей.

## Запуск проекта (без тестов и с тестами)

```bash
cp .env.example .env  # заполнить значения (но проще взять готовый в чате команды и подложить)
docker compose up -d --build
-----------------------------
docker compose up -d --build; if ($?) { docker compose --profile tests build --no-cache tests; docker compose --profile tests run --rm tests }
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
- notification_api:
  - Swagger (http://localhost:8004/docs)
  - Websocket мгновенных уведомлений (ws://localhost:8004/api/v1/notifications/ws?token=<access_token>)
- notification_admin_panel:
  - HTML-панель (http://localhost:8005/panel/)
  - Django-админка (http://localhost:8005/admin/)
  - Swagger (http://localhost:8005/api/v1/docs/)
- link_shortener_service:
  - Swagger (http://localhost:8006/docs)
  - Резолв короткой ссылки (http://localhost:8006/r/<code>)
- jaeger: http://localhost:16686
- kafka-ui: http://localhost:8090

Миграции БД авторизации применяются автоматически (one-shot сервис `auth_migrations`).

## Тесты

Все тесты живут в папке `tests/` (подпапка = тестируемый сервис: `admin_panel`, `async_api`, `auth_service`, `event_api`, `notification_api`, `link_shortener_service`, `analytics_etl`, `shared`, `ugc_service`) и запускаются одним контейнером. Нужен запущенный проект:

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

## Sentry

Мониторинг необработанных исключений — облачный [Sentry](https://sentry.io/) (бесплатный Developer-план). Подключён к сервисам с HTTP API — `async_api`, `auth_service`, `event_api`, `ugc_service`, `admin_panel`, `notification_api`, `link_shortener_service` — у каждого свой проект и свой DSN (issue #81). `analytics_etl` (фоновый Kafka-консьюмер, не API) сознательно не подключён.

1. На sentry.io завести отдельный проект под каждый сервис (Platform → Python/FastAPI для `async_api`/`auth_service`/`event_api`/`ugc_service`/`notification_api`/`link_shortener_service`, Python/Django для `admin_panel`).
2. В настройках каждого проекта Settings → Client Keys скопировать DSN.
3. Вставить DSN'ы в `.env` (`SENTRY_DSN_ASYNC_API`, `SENTRY_DSN_AUTH_SERVICE`, `SENTRY_DSN_EVENT_API`, `SENTRY_DSN_UGC_SERVICE`, `SENTRY_DSN_ADMIN_PANEL`, `SENTRY_DSN_NOTIFICATION_API`, `SENTRY_DSN_LINK_SHORTENER_SERVICE`) и перезапустить стек:

Без DSN конкретный сервис работает как обычно — просто не шлёт события в Sentry.

Запросы для проверки (только при DEBUG=True):

- async_api — http://localhost:8000/api/v1/_sentry_debug
- auth_service — http://localhost:8001/api/v1/_sentry_debug
- event_api — http://localhost:8002/api/v1/_sentry_debug
- ugc_service — http://localhost:8003/api/v1/_sentry_debug
- admin_panel — http://localhost/api/v1/_sentry_debug/
- notification_api — http://localhost:8004/api/v1/_sentry_debug
- link_shortener_service — http://localhost:8006/api/v1/_sentry_debug

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