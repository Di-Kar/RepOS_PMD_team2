"""Django authentication backend, делегирующий вход в /admin/ auth_service.

Права на Django admin даёт роль AUTH_SERVICE_ADMIN_ROLE (или is_superuser)
из ответа auth_service. Локальный Django User — не источник истины, а
зеркало для офлайн-фолбэка (см. AuthServiceUnavailable).
"""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from config.auth_service_client import (
    AuthServiceUnavailable,
    authenticate_via_auth_service,
)

logger = logging.getLogger(__name__)

User = get_user_model()


def _is_admin(auth_user) -> bool:
    return auth_user.is_superuser or settings.AUTH_SERVICE_ADMIN_ROLE in auth_user.roles


class AuthServiceBackend(ModelBackend):
    """Основной backend для /admin/: проверяет креды через auth_service."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None

        try:
            validate_email(username)
        except ValidationError:
            # auth_service требует email как логин — невалидный формат сразу
            # отдаём следующему backend'у, не тратя сетевой вызов.
            return None

        try:
            auth_user = authenticate_via_auth_service(username, password)
        except AuthServiceUnavailable:
            logger.warning(
                "auth_service недоступен, вход в admin_panel для %s — в деградированном режиме",
                username,
            )
            return self._authenticate_degraded(username, password)

        if auth_user is None:
            return None  # auth_service явно отверг учётные данные

        if not _is_admin(auth_user):
            logger.info("Пользователь %s аутентифицирован, но без прав администратора", username)
            return None

        return self._sync_local_user(auth_user, password)

    def _sync_local_user(self, auth_user, password: str):
        """Создаёт/обновляет локальное зеркало для офлайн-фолбэка.

        Гранулярных Django-прав нет: прошедший _is_admin получает полный
        доступ к admin, иначе staff без прав видел бы пустую панель.
        """
        first_name, _, last_name = auth_user.full_name.partition(" ")
        user, _ = User.objects.update_or_create(
            username=auth_user.email,
            defaults={
                "email": auth_user.email,
                "first_name": first_name,
                "last_name": last_name,
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )
        user.set_password(password)
        user.save(update_fields=["password"])
        return user

    def _authenticate_degraded(self, username: str, password: str):
        """auth_service недоступен: пускаем только тех, кто уже входил раньше
        (есть локальный кэш пароля/прав) и остаётся staff-пользователем."""
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return None
        if not user.is_active or not user.is_staff:
            return None
        if not user.check_password(password):
            return None
        return user
