# src/core/rate_limiter.py

import logging
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import settings

# Используем стандартный логгер, точно так же, как в main.py
logger = logging.getLogger(__name__)

def _get_user_key(request: Request) -> str:
    """
    Ключ лимита: user_id из request.state (заполняется middleware).
    Fallback на IP для анонимных запросов.
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(
    key_func=_get_user_key,
    storage_uri=settings.rate_limiter_storage_uri,
    strategy="fixed-window",
    default_limits=[],
)


def register_rate_limiter(app: FastAPI) -> None:
    """Подключить limiter и обработчик 429 к приложению."""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exception_handler)


async def _rate_limit_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Мы знаем, что здесь придет RateLimitExceeded, так как мы зарегистрировали хендлер именно для него.
    # Для безопасности можно добавить проверку или просто использовать str(exc)
    
    logger.warning(
        "rate_limit_exceeded",
        extra={
            "path": request.url.path,
            "method": request.method,
            "client": request.client.host if request.client else None,
            "user_id": getattr(request.state, "user_id", "anonymous"),
            "detail": str(exc),
        },
    )
    
    retry_after = "3600"
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": "Слишком много запросов. Пожалуйста, попробуйте позже.",
            "retry_after_seconds": int(retry_after),
        },
        headers={"Retry-After": retry_after},
        media_type="application/json",
    )