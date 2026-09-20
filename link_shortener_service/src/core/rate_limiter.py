"""Rate limiting. In-memory: у link_shortener_service нет своего общего
хранилища, поэтому лимиты считаются per-instance процесса (см. образец —
notification_api/src/core/rate_limiter.py)."""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.core.config import settings


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return get_remote_address(request) or (
        request.client.host if request.client else "unknown"
    )


limiter = Limiter(
    key_func=get_client_ip,
    default_limits=[settings.rate_limit_default],
    enabled=settings.rate_limit_enabled,
    headers_enabled=False,
)
