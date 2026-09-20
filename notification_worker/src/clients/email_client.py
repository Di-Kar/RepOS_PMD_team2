"""Отправка email через aiosmtplib с пулом переиспользуемых SMTP-соединений
(см. `SmtpPool` ниже) — по аналогии с asyncpg.Pool у Postgres
(src/db/postgres.py). В dev/test — MailHog (docker-compose сервис
`mailhog`), в проде переменные NOTIFICATION_WORKER_SMTP_* достаточно
переопределить реальными креденшелами, код транспорта не меняется."""

import asyncio
import logging
import re
import uuid
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Optional

import aiosmtplib

from src.core.config import settings
from src.core.errors import PermanentProcessingError, TransientProcessingError

logger = logging.getLogger(__name__)

# Простая синтаксическая проверка — отсекает явный мусор до похода в SMTP;
# не претендует на полную валидацию RFC 5322.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Не удалось установить соединение — письмо заведомо не начинало
# передаваться, повторять безопасно.
_CONNECT_ERRORS = (
    aiosmtplib.SMTPConnectError,
    aiosmtplib.SMTPConnectTimeoutError,
)

# Транспорт оборвался посреди уже начатого диалога с сервером — какая часть
# письма дошла, неизвестно (см. AmbiguousSendError).
_MID_SESSION_ERRORS = (
    aiosmtplib.SMTPServerDisconnected,
    OSError,
)


class PermanentSendError(PermanentProcessingError):
    """Письмо не может быть доставлено ни при каком числе попыток
    (невалидный адрес получателя, провайдер отклонил с постоянной ошибкой)."""


class TransientSendError(TransientProcessingError):
    """SMTP временно недоступен (таймаут, отказ в соединении, код 4xx)."""


class AmbiguousSendError(PermanentProcessingError):
    """Соединение оборвалось (или упал протокол) уже ПОСЛЕ того, как
    отправка письма началась (send_message на уже установленном
    соединении) — неизвестно, успел ли сервер принять письмо до обрыва.
    В отличие от TransientSendError, автоматический повтор здесь опасен
    (риск дубля — см. ревью), поэтому это не транзиентная, а постоянная
    ошибка: вызывающий (send_service) обязан остановить автообработку
    сообщения и завести его на ручной разбор, а не ретраить send_email
    вслепую."""


async def _connect() -> aiosmtplib.SMTP:
    client = aiosmtplib.SMTP(
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        timeout=settings.smtp_timeout,
        use_tls=settings.smtp_use_tls,
    )
    await client.connect()
    if settings.smtp_user:
        await client.login(settings.smtp_user, settings.smtp_password)
    return client


class SmtpPool:
    """Пул переиспользуемых SMTP-соединений. У aiosmtplib, в отличие от
    asyncpg, нет встроенного пулинга — `aiosmtplib.send()` (прежний вариант
    этого модуля) открывает и закрывает TCP/SMTP-соединение на каждое
    письмо. Здесь соединения создаются лениво, до `size` штук одновременно,
    и переживают между письмами.

    Разорванное соединение не возвращается в пул, а по возможности сразу
    заменяется свежим; если немедленное переподключение не удалось, пул
    временно уменьшается на одно место, не блокируя другие — а `acquire()`,
    прождав пул дольше `smtp_timeout`, сам открывает соединение напрямую
    (сверх пула), так что обработка сообщения не виснет навсегда даже если
    SMTP временно недоступен. Самовосстановление происходит по мере
    следующих `release()`, без отдельной фоновой задачи.

    Соединения, входящие в пул ("члены"), отслеживаются по `id(client)` в
    `_members` — это отличает их от временных сверх-пуловых соединений,
    которые `acquire()` открывает при таймауте ожидания: временные не
    учитываются в `_created` и не возвращаются в пул, а закрываются сразу
    после использования — иначе `_created` (число "постоянных" соединений)
    разошлось бы с реальным количеством живых соединений при устойчиво
    медленном SMTP, и пул мог бы расти неограниченно."""

    def __init__(self, size: int):
        self._size = size
        self._pool: asyncio.Queue[aiosmtplib.SMTP] = asyncio.Queue()
        self._created = 0
        self._lock = asyncio.Lock()
        self._members: set[int] = set()

    async def _connect_member(self) -> aiosmtplib.SMTP:
        client = await _connect()
        self._members.add(id(client))
        return client

    async def _acquire_or_create(self) -> aiosmtplib.SMTP:
        if not self._pool.empty():
            return self._pool.get_nowait()
        async with self._lock:
            if self._created < self._size:
                self._created += 1
                return await self._connect_member()
        return await self._pool.get()

    async def acquire(self) -> aiosmtplib.SMTP:
        try:
            client = await asyncio.wait_for(
                self._acquire_or_create(), timeout=settings.smtp_timeout
            )
        except asyncio.TimeoutError:
            # Пул исчерпан/завис дольше таймаута — не блокируем обработку
            # сообщения навечно, открываем временное соединение СВЕРХ пула
            # (не через _connect_member — оно не "член" пула, см. release()).
            return await _connect()
        if not await self._is_alive(client):
            # Соединение из пула успело умереть само по себе (сервер закрыл
            # его по простою между письмами) — не отдаём заведомо мёртвое.
            await self._discard(client)
            client = await self._connect_member()
        return client

    @staticmethod
    async def _is_alive(client: aiosmtplib.SMTP) -> bool:
        """Проверка "перед выдачей из пула" — одного `is_connected`
        недостаточно: он смотрит только на локальный транспорт, а тот
        остаётся "открытым", если соединение молча потеряно по дороге
        (NAT/файрвол выбросил простаивающую сессию, не прислав FIN). Без
        живого NOOP такое соединение уезжает в send_message и падает там
        обрывом, который send_email обязан трактовать как неопределённый
        исход (AmbiguousSendError) — то есть заводить на ручной разбор
        письмо, которое на самом деле ни разу не отправлялось."""
        if not client.is_connected:
            return False
        try:
            await client.noop()
        except Exception:  # noqa: BLE001 — любой сбой здесь означает "соединение негодно"
            return False
        return True

    async def release(self, client: aiosmtplib.SMTP) -> None:
        """Возвращает соединение в пул, если оно всё ещё живо (проверяется
        постфактум через `is_connected` — этого достаточно, чтобы отличить
        реальный обрыв транспорта от обычного 4xx/5xx SMTP-ответа, который
        сессию не разрывает) И является членом пула — временное
        сверх-пуловое соединение из acquire() всегда просто закрывается."""
        is_member = id(client) in self._members
        if client.is_connected:
            if is_member:
                await self._pool.put(client)
            else:
                await self._safe_quit(client)
            return
        if not is_member:
            await self._safe_quit(client)
            return
        await self._discard(client)
        try:
            fresh = await self._connect_member()
        except Exception as exc:  # noqa: BLE001 — переподключение best-effort
            logger.warning(f"SMTP reconnect failed while releasing pool slot: {exc}")
            return
        await self._pool.put(fresh)

    async def _discard(self, client: aiosmtplib.SMTP) -> None:
        self._members.discard(id(client))
        async with self._lock:
            self._created = max(self._created - 1, 0)
        await self._safe_quit(client)

    @staticmethod
    async def _safe_quit(client: aiosmtplib.SMTP) -> None:
        try:
            await client.quit()
        except Exception:  # noqa: BLE001
            pass

    async def close(self) -> None:
        while not self._pool.empty():
            client = self._pool.get_nowait()
            self._members.discard(id(client))
            await self._safe_quit(client)


_pool: Optional[SmtpPool] = None


async def init_smtp_pool() -> None:
    global _pool
    _pool = SmtpPool(size=settings.smtp_pool_size)
    logger.info(
        f"SMTP pool ready: {settings.smtp_host}:{settings.smtp_port} "
        f"(size={settings.smtp_pool_size})"
    )


async def close_smtp_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("SMTP pool closed.")


def get_smtp_pool() -> SmtpPool:
    if _pool is None:
        raise RuntimeError("SMTP pool is not initialized")
    return _pool


async def send_email(
    *, to: str | None, subject: str, body: str, notification_id: uuid.UUID
) -> None:
    if not to or not _EMAIL_RE.match(to):
        raise PermanentSendError(f"invalid recipient email: {to!r}")

    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = to
    message["Subject"] = subject
    # Детерминированный (по notification_id, не по попытке) Message-ID —
    # если это письмо всё же уйдёт повторно (см. AmbiguousSendError ниже),
    # провайдер/релей, умеющий дедуплицировать по Message-ID, получает эту
    # защиту "бесплатно", а по логам провайдера можно вручную сверить, что
    # реально было доставлено, при разборе notification_worker_dlq
    # (error_type=smtp_ambiguous, см. send_service.py). Сам по себе
    # заголовок ничего не гарантирует — «сырой» SMTP дедуп не поддерживает.
    # parseaddr — smtp_from_email допускает форму с display name
    # ("RepOS <noreply@...>"), из которой наивный rsplit('@') утащил бы в
    # домен закрывающую угловую скобку и сломал заголовок.
    _, from_addr = parseaddr(settings.smtp_from_email)
    domain = from_addr.rpartition("@")[2] or "repospmd.local"
    message["Message-ID"] = f"<{notification_id}@{domain}>"
    message.set_content(body)

    pool = get_smtp_pool()
    client = await pool.acquire()
    try:
        await client.send_message(message)
    except aiosmtplib.SMTPRecipientsRefused as exc:
        raise PermanentSendError(f"recipient refused: {to}: {exc}") from exc
    except aiosmtplib.SMTPResponseException as exc:
        if 500 <= exc.code < 600:
            raise PermanentSendError(
                f"SMTP permanent error {exc.code}: {exc.message}"
            ) from exc
        # Явный отказ сервера (4xx) — недвусмысленно "не принято", ретраить
        # безопасно (в отличие от обрыва ниже).
        raise TransientSendError(
            f"SMTP transient error {exc.code}: {exc.message}"
        ) from exc
    except _CONNECT_ERRORS as exc:
        # Соединение вообще не удалось установить (aiosmtplib пробовал
        # переподключиться внутри send_message) — письмо не начинало
        # передаваться, повторять безопасно.
        raise TransientSendError(f"SMTP connection error: {exc}") from exc
    except _MID_SESSION_ERRORS as exc:
        # Транспорт оборвался посреди диалога на соединении, живость
        # которого пул только что проверил (SmtpPool.acquire) — значит,
        # обрыв случился уже по ходу передачи письма и неизвестно, успел
        # ли сервер его принять. Автоповтор рискует задублировать
        # доставку, поэтому это не транзиентная, а требующая ручного
        # разбора ошибка (см. ревью).
        raise AmbiguousSendError(f"SMTP transport lost mid-session: {exc}") from exc
    except aiosmtplib.SMTPException as exc:
        # Прочие ошибки протокола на этом этапе — тоже уже после начала
        # диалога с сервером, по той же причине не ретраим автоматически.
        raise AmbiguousSendError(f"SMTP error: {exc}") from exc
    finally:
        # release() сам решает, жив ли клиент (client.is_connected) —
        # неважно, каким путём мы сюда попали (успех/4xx-5xx/обрыв).
        await pool.release(client)
