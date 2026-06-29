import logging
from abc import ABC, abstractmethod

from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class RetryPolicy(ABC):
    """Абстракция политики повторных попыток (DIP, ISP)."""

    @abstractmethod
    async def call(self, coro_func, *args, **kwargs):
        """Выполнить корутину с применением политики повторов."""


class ExponentialBackoffRetryPolicy(RetryPolicy):
    """Экспоненциальный backoff с настраиваемыми параметрами (SRP, OCP)."""

    def __init__(
        self,
        retryable_exceptions: tuple,
        attempts: int = 3,
        min_wait: float = 0.5,
        max_wait: float = 8.0,
    ):
        self._retryable_exceptions = retryable_exceptions
        self._attempts = attempts
        self._min_wait = min_wait
        self._max_wait = max_wait

    async def call(self, coro_func, *args, **kwargs):
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(self._retryable_exceptions),
            stop=stop_after_attempt(self._attempts),
            wait=wait_exponential(multiplier=1, min=self._min_wait, max=self._max_wait),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        ):
            with attempt:
                return await coro_func(*args, **kwargs)


class NoRetryPolicy(RetryPolicy):
    """Политика без повторов — для тестов и отключения ретраев (Null Object)."""

    async def call(self, coro_func, *args, **kwargs):
        return await coro_func(*args, **kwargs)
