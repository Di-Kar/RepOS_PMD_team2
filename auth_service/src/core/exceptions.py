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
