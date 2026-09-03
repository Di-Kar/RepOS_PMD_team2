"""Хэширование и проверка паролей (passlib + bcrypt)."""

import secrets
from typing import Optional

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Фиктивный хэш для несуществующего пользователя (защита от user enumeration по времени).
_DUMMY_PASSWORD_HASH = pwd_context.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    """Возвращает bcrypt-хэш пароля."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Сверяет пароль с хэшем. Некорректный хэш считается несовпадением."""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except ValueError:
        # В БД может лежать не-bcrypt значение.
        return False


def verify_password_or_dummy(
    plain_password: str, hashed_password: Optional[str]
) -> bool:
    """Как verify_password, но при hashed_password=None проверяет по фиктивному хэшу."""
    return verify_password(plain_password, hashed_password or _DUMMY_PASSWORD_HASH)
