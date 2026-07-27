"""Вход через соцсети — /api/v1/auth/oauth (только Google в этом спринте)."""
from datetime import datetime, timezone

from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.dependencies import get_current_user
from src.core.config import settings
from src.core.exceptions import (
    LastAuthMethodError,
    OAuthEmailNotVerifiedError,
    SocialAccountNotLinkedError,
)
from src.core.oauth import oauth
from src.core.rate_limiter import limiter
from src.db.postgres import get_session
from src.db.redis_db import get_redis
from src.models.entity import User
from src.models.schemas import TokenPair
from src.services.auth_service import AuthService
from src.services.oauth_service import OAuthService
from src.services.token_service import TokenService

router = APIRouter(prefix="/api/v1/auth/oauth")

_SUPPORTED_PROVIDERS = {"google"}


@router.get("/google/login", tags=["OAuth"])
@limiter.limit(settings.rate_limit_standard)
async def google_login(request: Request):
    """Редиректит на страницу согласия Google."""
    return await oauth.google.authorize_redirect(request, settings.google_redirect_uri)


@router.get("/google/callback", tags=["OAuth"], response_model=TokenPair)
@limiter.limit(settings.rate_limit_standard)
async def google_callback(
    request: Request,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> TokenPair:
    """Обмен code -> токены Google, поиск/создание пользователя, выдача своей пары токенов."""
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "oauth_failed", "message": str(exc)},
        )

    userinfo = token.get("userinfo") or {}
    if not userinfo.get("email"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "oauth_failed", "message": "Google did not return an email"},
        )

    # БД хранит naive UTC (TIMESTAMP WITHOUT TIME ZONE), как и остальные datetime-колонки проекта.
    expires_at = (
        datetime.fromtimestamp(token["expires_at"], tz=timezone.utc).replace(tzinfo=None)
        if token.get("expires_at")
        else None
    )
    try:
        user = await OAuthService(session).authenticate_or_register(
            provider="google",
            provider_user_id=userinfo["sub"],
            email=userinfo["email"],
            email_verified=bool(userinfo.get("email_verified")),
            full_name=userinfo.get("name"),
            access_token=token.get("access_token"),
            refresh_token=token.get("refresh_token"),
            token_expires_at=expires_at,
        )
    except OAuthEmailNotVerifiedError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "email_not_verified",
                "message": "Google email is not verified — cannot link to an existing account",
            },
        )

    roles = await AuthService(session).get_role_names(user.id)
    access_token, refresh_token = await TokenService(redis).create_token_pair(user, roles)
    return TokenPair(access_token=access_token, refresh_token=refresh_token)


@router.delete("/{provider}", tags=["OAuth"], status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(settings.rate_limit_moderate)
async def unlink_social_account(
    request: Request,
    provider: str = Path(
        description="Имя провайдера. Сейчас поддерживается только `google`.",
        examples=["google"],
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Отвязывает соцаккаунт от личного кабинета (доп. задание)."""
    if provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "unknown_provider", "message": f"Provider '{provider}' is not supported"},
        )
    try:
        await OAuthService(session).unlink(user, provider)
    except SocialAccountNotLinkedError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_linked", "message": f"No {provider} account linked"},
        )
    except LastAuthMethodError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "last_auth_method",
                "message": "Cannot unlink the only way to sign in — set a password first",
            },
        )
