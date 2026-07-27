"""Доменные исключения, транслируемые роутами в HTTP-ответы."""


class RoleNotFoundError(Exception):
    """Роль не найдена."""


class RoleAlreadyExistsError(Exception):
    """Роль с таким именем уже существует."""


class UserNotFoundError(Exception):
    """Пользователь не найден."""


class RoleAlreadyAssignedError(Exception):
    """Роль уже назначена пользователю."""


class RoleNotAssignedError(Exception):
    """Роль не была назначена пользователю."""


class UserAlreadyExistsError(Exception):
    """Пользователь с таким email уже зарегистрирован."""


class InvalidCredentialsError(Exception):
    """Неверный email или пароль."""


class InvalidTokenError(Exception):
    """Токен невалиден, истёк или его сессия завершена."""


class InvalidPasswordError(Exception):
    """Текущий пароль не совпадает (смена пароля)."""


class SocialAccountNotLinkedError(Exception):
    """У пользователя не привязан аккаунт этого провайдера."""


class LastAuthMethodError(Exception):
    """Нельзя отвязать последний способ входа (нет пароля и других соцаккаунтов)."""


class OAuthEmailNotVerifiedError(Exception):
    """Email от провайдера не подтверждён — привязка к существующему пользователю запрещена."""
