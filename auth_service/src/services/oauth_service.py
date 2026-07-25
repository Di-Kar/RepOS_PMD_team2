"""Вход через соцсети: связка SocialAccount <-> User, без своего OAuth-сервера
(auth_service выступает потребителем — обмен кода на токен делает authlib)."""
import secrets
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import LastAuthMethodError, SocialAccountNotLinkedError
from src.core.security import hash_password
from src.models.entity import SocialAccount, User


class OAuthService:
    """Находит/создаёт пользователя по данным от OAuth-провайдера."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_social_account(self, provider: str, provider_user_id: str) -> Optional[SocialAccount]:
        result = await self._session.execute(
            select(SocialAccount).where(
                SocialAccount.provider == provider,
                SocialAccount.provider_user_id == provider_user_id,
            )
        )
        return result.scalar_one_or_none()

    async def _get_user_by_login(self, email: str) -> Optional[User]:
        result = await self._session.execute(select(User).where(User.login == email))
        return result.scalar_one_or_none()

    async def authenticate_or_register(
        self,
        provider: str,
        provider_user_id: str,
        email: str,
        full_name: Optional[str],
        access_token: Optional[str],
        refresh_token: Optional[str],
        token_expires_at: Optional[datetime],
    ) -> User:
        """Возвращает пользователя, связанного с этим соцаккаунтом, создавая
        учётку/связь при первом входе.

        Порядок: уже была привязка этого provider_user_id -> берём владельца.
        Иначе — есть пользователь с таким email (заведён по паролю или другим
        провайдером) -> просто привязываем к нему. Иначе — заводим нового,
        с непригодным для входа по паролю случайным хэшем.
        """
        social_account = await self._get_social_account(provider, provider_user_id)
        if social_account is not None:
            social_account.access_token = access_token
            social_account.refresh_token = refresh_token
            social_account.token_expires_at = token_expires_at
            await self._session.commit()
            await self._session.refresh(social_account, attribute_names=["user"])
            return social_account.user

        user = await self._get_user_by_login(email)
        if user is None:
            first_name, _, last_name = (full_name or "").partition(" ")
            user = User(
                login=email,
                password=hash_password(secrets.token_urlsafe(32)),
                first_name=first_name or None,
                last_name=last_name or None,
                is_password_set=False,
            )
            self._session.add(user)
            await self._session.flush()  # нужен user.id для SocialAccount

        self._session.add(
            SocialAccount(
                user_id=user.id,
                provider=provider,
                provider_user_id=provider_user_id,
                email=email,
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=token_expires_at,
            )
        )
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def unlink(self, user: User, provider: str) -> None:
        """Отвязывает соцаккаунт. Запрещено, если это последний способ входа."""
        result = await self._session.execute(
            select(SocialAccount).where(
                SocialAccount.user_id == user.id, SocialAccount.provider == provider
            )
        )
        social_account = result.scalar_one_or_none()
        if social_account is None:
            raise SocialAccountNotLinkedError(provider)

        other_links = await self._session.scalar(
            select(SocialAccount.id).where(
                SocialAccount.user_id == user.id, SocialAccount.id != social_account.id
            )
        )
        if not user.is_password_set and other_links is None:
            raise LastAuthMethodError(str(user.id))

        await self._session.delete(social_account)
        await self._session.commit()
