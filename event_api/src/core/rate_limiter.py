"""Rate limiting (NFR-21). In-memory: у event_api нет своего хранилища
(диаграмма TO BE не предполагает Redis для этого сервиса), поэтому лимиты
считаются per-instance процесса, а не общие на все реплики."""
import logging

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.core.config import settings

logger = logging.getLogger("rate_limit")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return get_remote_address(request) or (request.client.host if request.client else "unknown")


limiter = Limiter(
    key_func=get_client_ip,
    default_limits=[settings.rate_limit_default],
    enabled=settings.rate_limit_enabled,
    headers_enabled=False,
)
