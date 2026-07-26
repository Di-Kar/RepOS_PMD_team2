"""Rate limiting configuration and utilities."""
import logging

from fastapi import Request, Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.status import HTTP_429_TOO_MANY_REQUESTS

from src.core.config import settings

# 1. Настройка логгера с гарантированным выводом (если корневой логгер не настроен)
logger = logging.getLogger("rate_limit")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    )
    logger.addHandler(handler)


def get_client_ip(request: Request) -> str:
    """
    Надежное получение IP-адреса клиента с учетом прокси (X-Forwarded-For).
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Берем первый IP в списке (оригинальный клиент)
        return forwarded_for.split(",")[0].strip()
    
    # Fallback на стандартный метод slowapi или client.host
    return get_remote_address(request) or (request.client.host if request.client else "unknown")


def get_user_identifier(request: Request) -> str:
    """
    Получение идентификатора для rate limiting.
    Для авторизованных: user:{user_id}
    Для неавторизованных: ip:{ip_address}
    """
    user_id = getattr(request.state, "user_id", None)
    
    if user_id:
        identifier = f"user:{user_id}"
        logger.debug(f"Rate limit key (auth): {identifier}")
        return identifier
    
    ip_address = get_client_ip(request)
    identifier = f"ip:{ip_address}"
    logger.debug(f"Rate limit key (anon): {identifier}")
    return identifier


def _disabled_limiter() -> Limiter:
    """Fallback того же типа с enabled=False: ошибка конфигурации/Redis
    не должна ронять auth_service целиком, только сам rate limiting."""
    return Limiter(key_func=get_user_identifier, enabled=False)


def create_limiter() -> Limiter:
    """
    Создание и настройка экземпляра rate limiter.
    """
    if not getattr(settings, "rate_limit_enabled", True):
        logger.warning("Rate limiting is disabled by settings")
        return _disabled_limiter()

    try:
        limiter = Limiter(
            key_func=get_user_identifier,
            storage_uri=settings.redis_dsn,
            storage_options={
                "socket_connect_timeout": 5,
                "socket_timeout": 5,
            },
            strategy=settings.rate_limit_strategy,
            default_limits=[settings.rate_limit_default],
            in_memory_fallback_enabled=True,
            # True требует Response из эндпоинта; у нас Pydantic-модели/dict.
            headers_enabled=False,
        )

        logger.info(
            f"Rate limiter initialized ({settings.rate_limit_strategy}) with Redis: {settings.redis_dsn}"
        )
        return limiter

    except Exception as e:
        logger.error(f"Failed to initialize rate limiter: {e}")
        logger.warning("Rate limiting will be disabled due to initialization error")
        return _disabled_limiter()


# Глобальный экземпляр лимитера
limiter = create_limiter()


def setup_rate_limit_middleware(app) -> None:
    @app.middleware("http")
    async def rate_limit_logging_middleware(request: Request, call_next):
        response: Response = await call_next(request)
        
        # Логируем только факты блокировки
        if response.status_code == HTTP_429_TOO_MANY_REQUESTS:
            user_id = getattr(request.state, "user_id", "anonymous")
            ip = get_client_ip(request)
            
            logger.warning(
                f"RATE LIMIT EXCEEDED | "
                f"user: {user_id} | "
                f"ip: {ip} | "
                f"method: {request.method} | "
                f"path: {request.url.path}"
            )
            
        return response
