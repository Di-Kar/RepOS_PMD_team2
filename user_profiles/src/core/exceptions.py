"""Доменные исключения, транслируемые роутами в HTTP-ответы."""


class ProfileNotFoundError(Exception):
    """Профиль пользователя не найден."""


class ProfileAlreadyExistsError(Exception):
    """Профиль для этого user_id уже создан."""


class PhoneAlreadyTakenError(Exception):
    """Телефон уже занят другим профилем."""
