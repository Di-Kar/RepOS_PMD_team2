import logging
import time
from functools import wraps
from typing import Callable, Tuple, Type

logger = logging.getLogger(__name__)

_start_sleep_time: float = 0.1
_factor: int = 2
_border_sleep_time: float = 10.0
_max_attempts: int = 0  # 0 = без ограничений


def configure(
    start_sleep_time: float = 0.1,
    factor: int = 2,
    border_sleep_time: float = 10.0,
    max_attempts: int = 0,
) -> None:
    """Устанавливает глобальные параметры backoff (вызывать один раз при старте)."""
    global _start_sleep_time, _factor, _border_sleep_time, _max_attempts
    _start_sleep_time = start_sleep_time
    _factor = factor
    _border_sleep_time = border_sleep_time
    _max_attempts = max_attempts


def backoff(exceptions: Tuple[Type[Exception], ...]) -> Callable:
    """Декоратор повторных попыток с экспоненциальной задержкой."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            sleep_time = _start_sleep_time
            attempt = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    attempt += 1
                    if _max_attempts and attempt >= _max_attempts:
                        logger.error(
                            'Функция %s завершилась ошибкой после %d попыток: %s',
                            func.__name__, attempt, e,
                        )
                        raise
                    log_fn = logger.error if attempt >= 5 else logger.warning
                    log_fn(
                        'Попытка %d для %s завершилась ошибкой: %s. Повтор через %.1f с',
                        attempt, func.__name__, e, sleep_time,
                    )
                    time.sleep(sleep_time)
                    sleep_time = min(sleep_time * _factor, _border_sleep_time)
        return wrapper
    return decorator
