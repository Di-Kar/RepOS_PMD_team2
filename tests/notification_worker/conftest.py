"""Фикстуры end-to-end тестов notification_worker (black-box): заявки идут
через настоящий notification_api (HTTP), а проверяем результат работы
воркера — письма в MailHog и статусы в notifications_db. По образцу
tests/notification_api/conftest.py и tests/auth_service/conftest.py."""

import asyncio
import base64
import os
import uuid
from datetime import datetime, timezone
from email.header import decode_header

import aiohttp
import asyncpg
import pytest_asyncio
from aiokafka import AIOKafkaProducer


def is_docker() -> bool:
    return os.path.exists('/.dockerenv')


# --- notification_api (создание заявок) --------------------------------------

NOTIFICATION_API_HOST = os.getenv(
    'NOTIFICATION_API_HOST', 'notification_api' if is_docker() else '127.0.0.1'
)
NOTIFICATION_API_PORT = int(
    os.getenv('NOTIFICATION_API_PORT', '8000' if is_docker() else '8004')
)
NOTIFICATIONS_BASE_URL = (
    f"http://{NOTIFICATION_API_HOST}:{NOTIFICATION_API_PORT}/api/v1/notifications"
)
NOTIFICATIONS_API_KEY = os.getenv('NOTIFICATIONS_API_KEY', '')
NOTIFICATIONS_HEADERS = (
    {"X-API-Key": NOTIFICATIONS_API_KEY} if NOTIFICATIONS_API_KEY else {}
)

# --- auth_service (регистрация тестовых пользователей) -----------------------

AUTH_API_HOST = os.getenv('AUTH_API_HOST', 'auth_service' if is_docker() else '127.0.0.1')
AUTH_API_PORT = int(os.getenv('AUTH_API_PORT', '8000' if is_docker() else '8001'))
AUTH_BASE_URL = f"http://{AUTH_API_HOST}:{AUTH_API_PORT}/api/v1/auth"

# --- user_profiles (ФИО тестового пользователя, S11_T4, issue #111) ----------

USER_PROFILES_API_HOST = os.getenv(
    'USER_PROFILES_API_HOST', 'user_profiles' if is_docker() else '127.0.0.1'
)
# Внутри docker-сети сервис слушает 8000, наружу проброшен как 8007.
USER_PROFILES_API_PORT = int(
    os.getenv('USER_PROFILES_API_PORT', '8000' if is_docker() else '8007')
)
USER_PROFILES_BASE_URL = (
    f"http://{USER_PROFILES_API_HOST}:{USER_PROFILES_API_PORT}/api/v1/profiles"
)

AUTH_POSTGRES_HOST = os.getenv('AUTH_POSTGRES_HOST', 'auth_postgres')
AUTH_POSTGRES_PORT = int(os.getenv('AUTH_POSTGRES_PORT', '5432'))
AUTH_POSTGRES_USER = os.getenv('AUTH_POSTGRES_USER', 'auth_user')
AUTH_POSTGRES_PASSWORD = os.getenv('AUTH_POSTGRES_PASSWORD', 'auth_password')
AUTH_POSTGRES_DB = os.getenv('AUTH_POSTGRES_DB', 'auth_db')

# --- notification_postgres (notifications_db — статусы воркера) --------------

NOTIFICATION_POSTGRES_HOST = os.getenv('NOTIFICATION_POSTGRES_HOST', 'notification_postgres')
NOTIFICATION_POSTGRES_PORT = int(os.getenv('NOTIFICATION_POSTGRES_PORT', '5432'))
NOTIFICATION_POSTGRES_USER = os.getenv('NOTIFICATION_POSTGRES_USER', 'notify_user')
NOTIFICATION_POSTGRES_PASSWORD = os.getenv('NOTIFICATION_POSTGRES_PASSWORD', 'notify_secret')
NOTIFICATION_POSTGRES_DB = os.getenv('NOTIFICATION_POSTGRES_DB', 'notifications_db')

# --- MailHog -------------------------------------------------------------------

MAILHOG_HOST = os.getenv('MAILHOG_HOST', 'mailhog' if is_docker() else '127.0.0.1')
MAILHOG_PORT = int(os.getenv('MAILHOG_PORT', '8025'))
MAILHOG_BASE_URL = f"http://{MAILHOG_HOST}:{MAILHOG_PORT}"

# --- Kafka (публикация напрямую в notifications.ready.v1 для точечного
# теста идемпотентности send-стадии, в обход render-стадии) ------------------

KAFKA_BOOTSTRAP_SERVERS = os.getenv(
    'NOTIFICATION_WORKER_KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092'
)
TOPIC_READY = os.getenv('NOTIFICATION_WORKER_KAFKA_TOPIC_READY', 'notifications.ready.v1')


@pytest_asyncio.fixture(name='kafka_ready_producer')
async def kafka_ready_producer():
    import json

    producer = AIOKafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8"),
    )
    await producer.start()

    async def _publish(key: str, value: dict) -> None:
        await producer.send_and_wait(TOPIC_READY, key=key, value=value)

    yield _publish
    await producer.stop()


def make_notification_request(**overrides) -> dict:
    """Валидная заявка по контракту docs/notification_requests_contract.md
    §3 — по умолчанию свободный формат (text_override), без шаблона."""
    request = {
        "request_id": str(uuid.uuid4()),
        "source_service": "notification-worker-e2e-test",
        "channel": "email",
        "text_override": "Тестовое сообщение",
        "subject_override": "Тестовая тема",
        "context": {},
        "recipient_ids": [str(uuid.uuid4())],
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    request.update(overrides)
    return request


@pytest_asyncio.fixture(name='session')
async def session():
    async with aiohttp.ClientSession() as http_session:
        yield http_session


async def post_notification(session: aiohttp.ClientSession, body: dict) -> tuple:
    async with session.post(
        NOTIFICATIONS_BASE_URL, json=body, headers=NOTIFICATIONS_HEADERS
    ) as response:
        return response.status, await response.json()


async def _post_with_retry_on_429(session, url, json_body, headers=None) -> tuple:
    while True:
        async with session.post(url, json=json_body, headers=headers) as response:
            if response.status == 429:
                retry_after = float(response.headers.get('Retry-After', 2))
                await response.read()
            else:
                return response.status, await response.json()
        await asyncio.sleep(retry_after + 0.2)


@pytest_asyncio.fixture(name='register_user')
def register_user(session: aiohttp.ClientSession):
    """Фабрика: `user = await register_user(full_name="Иван Иванов")` ->
    {"id", "email", "full_name"} — реальный пользователь в auth_service.

    ФИО с S11_T4 (issue #111) живёт в user_profiles, а не в auth_service —
    auth_service/register больше не принимает full_name, поэтому фабрика
    дополнительно логинится и создаёт профиль в user_profiles, чтобы
    рендер-стадия воркера действительно обогащала профиль по сети (через
    auth_service → user_profiles), а не по заглушке."""

    async def _register(full_name: str = "Тест Тестов") -> dict:
        email = f"worker-e2e-{uuid.uuid4().hex}@example.com"
        password = "WorkerE2ePass123!"
        status, body = await _post_with_retry_on_429(
            session,
            f"{AUTH_BASE_URL}/register",
            {"email": email, "password": password},
        )
        assert status == 201, f"registration failed: {status} {body}"

        status, tokens = await _post_with_retry_on_429(
            session,
            f"{AUTH_BASE_URL}/login",
            {"email": email, "password": password},
        )
        assert status == 200, f"login failed: {status} {tokens}"

        first_name, _, last_name = full_name.partition(" ")
        phone = f"+7999{uuid.uuid4().int % 10_000_000:07d}"
        status, profile = await _post_with_retry_on_429(
            session,
            f"{USER_PROFILES_BASE_URL}/me",
            {"first_name": first_name, "last_name": last_name or "-", "phone": phone},
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert status == 201, f"profile creation failed: {status} {profile}"

        return {"id": body["id"], "email": email, "full_name": full_name}

    return _register


@pytest_asyncio.fixture(name='auth_db_conn')
async def auth_db_conn():
    conn = await asyncpg.connect(
        host=AUTH_POSTGRES_HOST,
        port=AUTH_POSTGRES_PORT,
        user=AUTH_POSTGRES_USER,
        password=AUTH_POSTGRES_PASSWORD,
        database=AUTH_POSTGRES_DB,
    )
    yield conn
    await conn.close()


@pytest_asyncio.fixture(name='db_conn')
async def db_conn():
    """Подключение к notifications_db — тем же таблицам, что заполняет
    notification_worker (notifications/notification_history/notification_log,
    см. notification_worker/src/db/queries.py)."""
    conn = await asyncpg.connect(
        host=NOTIFICATION_POSTGRES_HOST,
        port=NOTIFICATION_POSTGRES_PORT,
        user=NOTIFICATION_POSTGRES_USER,
        password=NOTIFICATION_POSTGRES_PASSWORD,
        database=NOTIFICATION_POSTGRES_DB,
    )
    yield conn
    await conn.close()


async def wait_until(predicate, *, timeout: float = 20.0, interval: float = 0.5):
    """Опрашивает `predicate()` (корутина, возвращающая truthy значение или
    None/False) пока не получит непустой результат или не истечёт timeout.
    Возвращает результат predicate() либо None."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        result = await predicate()
        if result:
            return result
        await asyncio.sleep(interval)
    return None


class MailhogClient:
    def __init__(self, session: aiohttp.ClientSession):
        self._session = session

    async def clear(self) -> None:
        async with self._session.delete(f"{MAILHOG_BASE_URL}/api/v1/messages") as resp:
            await resp.read()

    async def messages(self) -> list[dict]:
        async with self._session.get(f"{MAILHOG_BASE_URL}/api/v2/messages?limit=200") as resp:
            # MailHog отвечает Content-Type: text/json (не application/json) —
            # aiohttp.json() иначе падает на строгой проверке mimetype.
            data = await resp.json(content_type=None)
            return data.get("items", [])

    async def find_by_recipient(self, email: str, *, subject: str | None = None) -> list[dict]:
        """recipient-only фильтр не различает тестовое письмо и
        приветственное письмо auth_service (register_user() всегда триггерит
        send_welcome_with_confirmation в фоне на тот же адрес, см.
        auth_service/src/services/registration_notifications.py) — если тест
        чувствителен к конкретному письму, передавайте `subject` (сравнение
        после RFC 2047-декодирования, см. `subject()`)."""
        items = await self.messages()
        matching = [
            item
            for item in items
            if any(
                f"{to.get('Mailbox')}@{to.get('Domain')}".lower() == email.lower()
                for to in item.get("To", [])
            )
        ]
        if subject is not None:
            matching = [item for item in matching if self.subject(item) == subject]
        return matching

    async def wait_for_message(
        self, email: str, *, subject: str | None = None, timeout: float = 20.0
    ) -> dict | None:
        async def _check():
            found = await self.find_by_recipient(email, subject=subject)
            return found[0] if found else None

        return await wait_until(_check, timeout=timeout)

    @staticmethod
    def subject(item: dict) -> str:
        """Декодирует Subject-заголовок из RFC 2047 encoded-word
        (`=?utf-8?b?...?=`) в обычную строку — MailHog отдаёт заголовки как
        есть, без декодирования."""
        headers = item.get("Content", {}).get("Headers", {})
        values = headers.get("Subject", [])
        raw = values[0] if values else ""
        decoded_parts = decode_header(raw)
        return "".join(
            part.decode(encoding or "utf-8") if isinstance(part, bytes) else part
            for part, encoding in decoded_parts
        )

    @staticmethod
    def body(item: dict) -> str:
        """Декодирует тело письма — aiosmtplib/EmailMessage кодирует
        нелатинский текст base64 (Content-Transfer-Encoding: base64),
        MailHog отдаёt его как есть."""
        content = item.get("Content", {})
        raw = content.get("Body", "")
        encoding = content.get("Headers", {}).get("Content-Transfer-Encoding", [""])[0]
        if encoding.lower() == "base64":
            return base64.b64decode(raw).decode("utf-8", errors="replace")
        return raw


@pytest_asyncio.fixture(name='mailhog')
async def mailhog(session: aiohttp.ClientSession):
    client = MailhogClient(session)
    await client.clear()
    yield client
