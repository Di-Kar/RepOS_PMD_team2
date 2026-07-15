"""Хэширование и проверка паролей (passlib + bcrypt)."""
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


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
