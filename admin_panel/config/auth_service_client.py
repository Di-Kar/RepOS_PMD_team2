"""HTTP-клиент к auth_service для логина администратора и получения его ролей.

Пароль проверяется через POST /login + GET /profile, не локально. Локальный
Django User — офлайн-кэш на случай недоступности (см. auth_backends.py).
"""
import logging
from dataclasses import dataclass, field
from typing import List, Optional

import requests
from django.conf import settings

from config.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

_breaker = CircuitBreaker(
    failure_threshold=settings.AUTH_SERVICE_BREAKER_FAILURE_THRESHOLD,
    reset_timeout=settings.AUTH_SERVICE_BREAKER_RESET_TIMEOUT,
)


@dataclass
class AuthServiceUser:
    """Данные пользователя, подтверждённые auth_service."""

    id: str
    email: str
    full_name: str = ""
    roles: List[str] = field(default_factory=list)
    is_superuser: bool = False


class AuthServiceUnavailable(Exception):
    """auth_service недоступен или не отвечает (таймаут/сеть/breaker открыт)."""


def authenticate_via_auth_service(email: str, password: str) -> Optional[AuthServiceUser]:
    """Проверяет логин/пароль в auth_service, возвращает данные пользователя.

    None — сервис ответил, но отклонил запрос (4xx: неверный пароль, невалидный
    email и т.п.). AuthServiceUnavailable — сервис реально недоступен (сеть/5xx).
    """
    if not _breaker.allow_request():
        logger.warning("auth_service circuit breaker открыт, пропускаем запрос")
        raise AuthServiceUnavailable("circuit breaker open")

    base_url = settings.AUTH_SERVICE_URL
    timeout = settings.AUTH_SERVICE_TIMEOUT
    try:
        login_response = requests.post(
            f"{base_url}/login",
            json={"email": email, "password": password},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        _breaker.record_failure()
        raise AuthServiceUnavailable(str(exc)) from exc

    if login_response.status_code >= 500:
        _breaker.record_failure()
        raise AuthServiceUnavailable(f"login вернул {login_response.status_code}")
    _breaker.record_success()  # сервис ответил — он жив, вне зависимости от исхода
    if login_response.status_code != 200:
        return None  # неверные креды / невалидный запрос (401, 422, ...)

    access_token = login_response.json()["access_token"]

    try:
        profile_response = requests.get(
            f"{base_url}/profile",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        _breaker.record_failure()
        raise AuthServiceUnavailable(str(exc)) from exc

    if profile_response.status_code >= 500:
        _breaker.record_failure()
        raise AuthServiceUnavailable(f"profile вернул {profile_response.status_code}")
    _breaker.record_success()
    if profile_response.status_code != 200:
        return None

    data = profile_response.json()
    return AuthServiceUser(
        id=str(data["id"]),
        email=data["email"],
        full_name=data.get("full_name", ""),
        roles=data.get("roles") or [],
        is_superuser=data.get("is_superuser", False),
    )
