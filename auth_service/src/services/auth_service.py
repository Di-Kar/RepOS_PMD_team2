"""Бизнес-логика аутентификации: регистрация, вход, профиль, история входов."""
import uuid
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import (
    InvalidCredentialsError,
    InvalidPasswordError,
    UserAlreadyExistsError,
)
from src.core.security import hash_password, verify_password, verify_password_or_dummy
from src.core.utils import get_device_type
from src.models.entity import LoginHistory, Role, User, UserRole


def split_full_name(full_name: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Делит full_name на first_name/last_name по первому пробелу."""
    if not full_name or not full_name.strip():
        return None, None
    parts = full_name.strip().split(" ", 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else None
    return first_name, last_name


def join_full_name(user: User) -> str:
    """Собирает full_name из first_name/last_name."""
    return " ".join(part for part in (user.first_name, user.last_name) if part)


class AuthService:
    """Операции над пользователем: регистрация, вход, профиль, пароль, история."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(self, email: str, password: str, full_name: Optional[str]) -> User:
        """Создаёт пользователя. Email хранится в колонке login."""
        first_name, last_name = split_full_name(full_name)
        user = User(
            login=email,
            password=hash_password(password),
            first_name=first_name,
            last_name=last_name,
        )
        self._session.add(user)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            # 23505 = unique_violation (SQLSTATE); другие IntegrityError — не
            # "email занят", их нельзя маскировать под конфликт логина.
            if getattr(getattr(exc, "orig", None), "sqlstate", None) == "23505":
                raise UserAlreadyExistsError(email)
            raise
        await self._session.refresh(user)
        return user

    async def get_by_login(self, email: str) -> Optional[User]:
        result = await self._session.execute(select(User).where(User.login == email))
        return result.scalar_one_or_none()

    async def authenticate(
        self,
        email: str,
        password: str,
        user_agent: Optional[str],
        ip_address: Optional[str],
    ) -> User:
        """Проверяет учётные данные и пишет запись в историю входов.

        Неудачная попытка для существующего пользователя тоже фиксируется
        (success=False) — по ней можно обнаружить подбор пароля. Пароль
        проверяется даже для несуществующего email (по фиктивному хэшу).
        """
        user = await self.get_by_login(email)
        success = verify_password_or_dummy(password, user.password if user is not None else None)
        if user is None or not user.is_active:
            raise InvalidCredentialsError(email)

        device_type = get_device_type(user_agent)
        
        # Опционально: можно сгенерировать простой fingerprint
        fingerprint = f"{ip_address}_{device_type}" if ip_address else None

        self._session.add(
            LoginHistory(
                user_id=user.id,
                user_agent=user_agent,
                ip_address=ip_address,
                fingerprint=fingerprint,
                success=success,
                user_device_type=device_type,
            )
        )
       
        await self._session.commit()

        if not success:
            raise InvalidCredentialsError(email)
        
        return user

    async def get_role_names(self, user_id: uuid.UUID) -> List[str]:
        """Имена ролей пользователя — кладутся в payload access-токена."""
        result = await self._session.execute(
            select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(
                UserRole.user_id == user_id
            )
        )
        return list(result.scalars())

    async def update_full_name(self, user: User, full_name: str) -> User:
        """Обновляет ФИО (email по спеке изменить нельзя)."""
        user.first_name, user.last_name = split_full_name(full_name)
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def change_password(self, user: User, current_password: str, new_password: str) -> None:
        if not verify_password(current_password, user.password):
            raise InvalidPasswordError(user.id)
        user.password = hash_password(new_password)
        await self._session.commit()

    async def get_login_history(
        self, user_id: uuid.UUID, page: int, size: int
    ) -> Tuple[List[LoginHistory], int]:
        """Страница истории входов (свежие первыми) и общее число записей."""
        total = await self._session.scalar(
            select(func.count()).select_from(LoginHistory).where(LoginHistory.user_id == user_id)
        )
        result = await self._session.execute(
            select(LoginHistory)
            .where(LoginHistory.user_id == user_id)
            .order_by(LoginHistory.login_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        return list(result.scalars()), int(total or 0)
