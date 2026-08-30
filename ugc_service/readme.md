# ugc_service — Сервис пользовательского контента

Сервис для управления закладками, лайками и рецензиями пользователей к фильмам.
Использует шардированный кластер MongoDB (2 шарда × 3 реплики + 3 config server + 2 mongos) и Beanie (Motor async API).

## Архитектура

```
Клиент → ugc_service → MongoDB Cluster (11 контейнеров)
              ↓
         async_api (HTTP-запросы для карточки фильма)
```

### MongoDB кластер (11 контейнеров)

| Контейнер | Роль | Порт |
|-----------|------|------|
| `mongo_config-0`, `mongo_config-1`, `mongo_config-2` | Config Servers (реплика сет "config") | 27017 |
| `mongo_shard1-0`, `mongo_shard1-1`, `mongo_shard1-2` | Shard 1 (реплика сет "shard1") | 27017 |
| `mongo_shard2-0`, `mongo_shard2-1`, `mongo_shard2-2` | Shard 2 (реплика сет "shard2") | 27017 |
| `mongo_mongos-0`, `mongo_mongos-1` | Mongos Routers (внешний доступ) | 27017, 27018 |

> **Примечание:** Контейнеры mongos доступны по портам `27017` и `27018`. Все остальные контейнеры MongoDB используют внутренний порт `27017` и доступны только внутри Docker network.

### Shard Key стратегия

| Коллекция | Shard Key | Обоснование |
|-----------|-----------|-------------|
| `bookmarks` | `{user_id: "hashed"}` | Равномерное распределение, один пользователь не перегружает шард |
| `likes` | `{user_id: "hashed"}` | Один документ на пользователя-фильм, хэширование |
| `reviews` | `{film_id: 1}` | Все рецензии к фильму на одном шарде, эффективные агрегации |
| `review_votes` | `{review_id: 1}` | Привязка к рецензиям |

## API Endpoints

### Авторизация (`/api/v1/auth`)

| Метод | Endpoint | Описание |
|-------|----------|----------|
| POST | `/api/v1/auth/login` | Получить JWT-токен (email + password в JSON body) |

### Закладки (`/api/v1/bookmarks`)

| Метод | Endpoint | Описание |
|-------|----------|----------|
| POST | `/api/v1/bookmarks?film_id={id}` | Добавить фильм в закладки |
| DELETE | `/api/v1/bookmarks/{film_id}` | Удалить фильм из закладок |
| GET | `/api/v1/bookmarks?page=1&page_size=20` | Список закладок пользователя |

### Лайки (`/api/v1/likes`)

| Метод | Endpoint | Описание |
|-------|----------|----------|
| POST | `/api/v1/likes?film_id={id}&rating=8` | Добавить/обновить оценку (0-10) |
| DELETE | `/api/v1/likes/{film_id}` | Удалить оценку |
| GET | `/api/v1/likes/{film_id}` | Статистика: total_ratings, average_rating |

### Рецензии (`/api/v1/reviews`)

| Метод | Endpoint | Описание |
|-------|----------|----------|
| POST | `/api/v1/reviews?film_id={id}&title=...&text=...&rating=8` | Создать рецензию |
| GET | `/api/v1/reviews?film_id={id}&sort=likes_count&page=1&page_size=20` | Список рецензий (сортировка: likes_count, published_at, rating) |
| GET | `/api/v1/reviews/{review_id}` | Детали рецензии |
| PUT | `/api/v1/reviews/{review_id}?title=...&text=...&rating=...` | Обновить рецензию (только автор) |
| DELETE | `/api/v1/reviews/{review_id}` | Удалить рецензию (только автор) |
| POST | `/api/v1/reviews/{review_id}/vote?is_like=true` | Голос за/против рецензии |

> **Авторизация:** Все endpoints (кроме `/api/v1/auth/login` и `/health`) требуют JWT-токен.
> Получите токен через `POST /api/v1/auth/login` с телом `{"email": "...", "password": "..."}`.

## Swagger UI

Доступен по адресу: **`http://localhost:8003/docs`**

Для тестирования ручек вручную:

1. Откройте Swagger UI
2. Нажмите кнопку **"Authorize"** (замок 🔒 вверху справа)
3. Получите токен через `POST /api/v1/auth/login`:
   - Нажмите "Try it out"
   - Введите email и пароль в JSON body
   - Нажмите "Execute"
   - Скопируйте `access_token` из ответа
4. Вставьте токен в поле Authorize (без префикса `Bearer `)
5. Нажмите "Authorize" → "Close"
6. Все endpoint'ы теперь автоматически отправляют токен

## Интеграция с async_api

async_api вызывает ugc_service для отображения данных в карточке фильма:

```
async_api → GET http://ugc_service:8000/api/v1/likes/{film_id}
async_api → GET http://ugc_service:8000/api/v1/bookmarks?film_id={id}
async_api → GET http://ugc_service:8000/api/v1/reviews?film_id={id}&sort=likes_count&size=5
```

Pydantic response-модели определены в `shared/ugc_schemas.py` — используются обоими сервисами.

## Запуск

### 1. Запуск MongoDB кластера

```bash
docker compose up -d --build
```

Кластер инициализируется автоматически через скрипт `docker/setup_mongo_cluster.sh`:
- Создание реплика сета для config, shard1, shard2
- Регистрация шардов в mongos
- Включение sharding для базы `ugc_service`

### 2. Запуск сервиса

Сервис запускается автоматически как часть `docker compose up`.

### 3. Проверка

```bash
# Healthcheck
curl http://localhost:8003/health

# Swagger UI
open http://localhost:8003/docs
```

### 4. Остановка

```bash
docker compose down -v --remove-orphans
```

## Тесты

```bash
# Все тесты проекта
docker compose run --rm tests

# Только тесты ugc_service
docker compose run --rm tests pytest /tests/ugc_service -v

# E2E тесты (все API endpoints + проверка MongoDB)
docker compose run --rm tests pytest /tests/ugc_service/test_ugc_e2e.py -v
```

### E2E тесты

14 тестов покрывают все API endpoints и подтверждают сохранение данных в MongoDB:

| Класс | Тесты |
|-------|-------|
| `TestBookmarksE2E` | add, get, remove, check MongoDB |
| `TestLikesE2E` | add, get stats, remove, check MongoDB |
| `TestReviewsE2E` | create, get list, get detail, vote, check MongoDB, vote check MongoDB |

## Структура

```
ugc_service/
├── Dockerfile
├── requirements.txt
├── readme.md
├── src/
│   ├── main.py            # FastAPI приложение + Swagger security
│   ├── config.py          # Настройки (pydantic-settings)
│   ├── logger.py          # Логирование
│   ├── db/
│   │   ├── connection.py  # Beanie + Motor подключение
│   │   └── init_db.py     # Sharding + indexes
│   ├── models/
│   │   ├── bookmark.py    # Bookmark (Beanie Document)
│   │   ├── like.py        # Like
│   │   └── review.py      # Review + ReviewVote
│   ├── api/v1/
│   │   ├── auth_proxy.py  # Прокси авторизации к auth_service
│   │   ├── bookmarks.py   # CRUD закладок
│   │   ├── likes.py       # CRUD лайков
│   │   └── reviews.py     # CRUD рецензий
│   ├── api/dependencies.py # Аутентификация, пагинация
│   └── services/
│       ├── bookmark_service.py
│       ├── like_service.py
│       └── review_service.py
└── tests/
    └── ugc_service/
        ├── test_ugc_e2e.py         # E2E тесты (14 тестов)
        ├── test_services.py        # Unit тесты сервисов
        └── test_ugc_schemas.py     # Тесты схем
```

## Зависимости

```
fastapi==0.111.0
beanie==1.26.0
pydantic-settings==2.12.0
pydantic==2.9.2
gunicorn==23.0.0
uvicorn[standard]==0.30.0
httpx==0.27.0
motor==3.6.0
```

## Переменные окружения

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `MONGO_URI` | `mongodb://mongo_mongos-0:27017,mongo_mongos-1:27017` | URI подключения к mongos |
| `MONGO_DB` | `ugc_service` | Имя базы данных |
| `AUTH_SERVICE_URL` | `http://auth_service:8000/api/v1/auth` | URL auth_service |
| `AUTH_REQUEST_TIMEOUT` | `1.5` | Таймаут запросов к auth_service |
| `DEBUG` | `False` | Режим отладки |

## SLA

Все операции укладываются в требование **< 200 мс** (подтверждено бенчмарком `storage_research/`):

| Операция | Время |
|----------|-------|
| Read by ID | ~1.5 мс |
| Write (insert/update) | ~4 мс |
| Агрегация (лайки) | < 10 мс |
| Поиск с пагинацией | < 20 мс |
