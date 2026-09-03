"""Простой circuit breaker: CLOSED -> (N неудач) -> OPEN -> (reset_timeout)
-> half-open (пробный запрос) -> CLOSED/OPEN. Состояние в памяти процесса
(не шарится между воркерами, но каждый деградирует независимо).
"""

import time
from typing import Optional


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, reset_timeout: float = 30.0) -> None:
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._failures = 0
        self._opened_at: Optional[float] = None

    def allow_request(self) -> bool:
        if self._opened_at is None:
            return True
        if time.monotonic() - self._opened_at >= self._reset_timeout:
            return True  # half-open: пробуем один запрос
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._failure_threshold:
            self._opened_at = time.monotonic()
