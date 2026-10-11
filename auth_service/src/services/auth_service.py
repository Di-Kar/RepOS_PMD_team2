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


class AuthService:
    """Операции над пользователем: регистрация, вход, профиль, пароль, история."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(
        self, email: str, password: str
    ) -> User:
        """Создаёт пользователя. Email хранится в колонке login.
        ФИО больше не передаётся и не сохраняется в auth_service (S11_T4)."""
        user = User(
            login=email,
            password=hash_password(password),
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
        success = verify_password_or_dummy(
            password, user.password if user is not None else None
        )
        if user is None or not user.is_active:
            raise InvalidCredentialsError(email)

        device_type = get_device_type(user_agent) or "web"

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
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
        return list(result.scalars())

    async def change_password(
        self, user: User, current_password: str, new_password: str
    ) -> None:
        if not verify_password(current_password, user.password):
            raise InvalidPasswordError(user.id)
        user.password = hash_password(new_password)
        await self._session.commit()

    async def get_login_history(
        self, user_id: uuid.UUID, page: int, size: int
    ) -> Tuple[List[LoginHistory], int]:
        """Страница истории входов (свежие первыми) и общее число записей."""
        total = await self._session.scalar(
            select(func.count())
            .select_from(LoginHistory)
            .where(LoginHistory.user_id == user_id)
        )
        result = await self._session.execute(
            select(LoginHistory)
            .where(LoginHistory.user_id == user_id)
            .order_by(LoginHistory.login_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        return list(result.scalars()), int(total or 0)