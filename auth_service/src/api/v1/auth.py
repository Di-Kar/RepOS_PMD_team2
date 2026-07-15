"""Роуты аутентификации и профиля — /api/v1/auth (по openapi_auth.yaml)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.dependencies import get_current_user, get_token_payload
from src.core.exceptions import (
    InvalidCredentialsError,
    InvalidPasswordError,
    InvalidTokenError,
    UserAlreadyExistsError,
)
from src.db.postgres import get_session
from src.db.redis_db import get_redis
from src.models.entity import User
from src.models.schemas import (
    ChangePasswordRequest,
    LoginHistoryItem,
    LoginHistoryResponse,
    MessageResponse,
    RefreshRequest,
    TokenPair,
    TokenPayload,
    UserLoginRequest,
    UserRegisterRequest,
    UserRegisterResponse,
    UserResponse,
    UserUpdateRequest,
)
from src.services.auth_service import AuthService, join_full_name
from src.services.token_service import TokenService

router = APIRouter(prefix="/api/v1/auth")


def _user_response(user: User) -> dict:
    return {"id": user.id, "email": user.login, "full_name": join_full_name(user)}


@router.post(
    "/register",
    tags=["Authentication"],
    response_model=UserRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: UserRegisterRequest,
    session: AsyncSession = Depends(get_session),
) -> UserRegisterResponse:
    service = AuthService(session)
    try:
        user = await service.register(payload.email, payload.password, payload.full_name)
    except UserAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "email_taken", "message": "Email already registered"},
        )
    return UserRegisterResponse(**_user_response(user), created_at=user.created_at)


@router.post("/login", tags=["Authentication"], response_model=TokenPair)
async def login(
    payload: UserLoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> TokenPair:
    service = AuthService(session)
    try:
        user = await service.authenticate(
            payload.email,
            payload.password,
            user_agent=request.headers.get("User-Agent"),
            ip_address=request.client.host if request.client else None,
        )
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_credentials", "message": "Invalid email or password"},
        )

    roles = await service.get_role_names(user.id)
    access_token, refresh_token = await TokenService(redis).create_token_pair(user, roles)
    return TokenPair(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", tags=["Tokens"], response_model=TokenPair)
async def refresh(
    payload: RefreshRequest,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> TokenPair:
    """Ротация: старый refresh гасится, выдаётся новая пара в той же сессии."""
    token_service = TokenService(redis)
    try:
        token_payload = await token_service.validate_refresh_token(payload.refresh_token)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "message": str(exc)},
        )

    user = await session.get(User, uuid.UUID(token_payload.sub))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "message": "User not found or inactive"},
        )

    roles = await AuthService(session).get_role_names(user.id)
    access_token, refresh_token = await token_service.create_token_pair(
        user, roles, session_id=token_payload.session_id
    )
    return TokenPair(access_token=access_token, refresh_token=refresh_token)


@router.post("/logout", tags=["Tokens"], status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    token_payload: TokenPayload = Depends(get_token_payload),
    redis: Redis = Depends(get_redis),
) -> None:
    """Завершает текущую сессию: refresh отзывается, access этой сессии перестаёт работать."""
    await TokenService(redis).revoke_session(token_payload.sub, token_payload.session_id)


@router.post("/logout-all", tags=["Tokens"], status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    token_payload: TokenPayload = Depends(get_token_payload),
    redis: Redis = Depends(get_redis),
) -> None:
    """Завершает все сессии пользователя, кроме текущей."""
    await TokenService(redis).revoke_all_sessions(
        token_payload.sub, except_session_id=token_payload.session_id
    )


@router.get("/profile", tags=["Profile"], response_model=UserResponse)
async def get_profile(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse(**_user_response(user))


@router.put("/profile", tags=["Profile"], response_model=UserResponse)
async def update_profile(
    payload: UserUpdateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    user = await AuthService(session).update_full_name(user, payload.full_name)
    return UserResponse(**_user_response(user))


@router.post("/change-password", tags=["Profile"], response_model=MessageResponse)
async def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    token_payload: TokenPayload = Depends(get_token_payload),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> MessageResponse:
    try:
        await AuthService(session).change_password(
            user, payload.current_password, payload.new_password
        )
    except InvalidPasswordError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_password",
                "message": "Current password is incorrect",
                "field": "current_password",
            },
        )
    # После смены пароля все остальные сессии завершаются — текущая остаётся.
    await TokenService(redis).revoke_all_sessions(
        token_payload.sub, except_session_id=token_payload.session_id
    )
    return MessageResponse(message="Password changed successfully")


@router.get("/history", tags=["Profile"], response_model=LoginHistoryResponse)
async def login_history(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> LoginHistoryResponse:
    items, total = await AuthService(session).get_login_history(user.id, page, size)
    pages = (total + size - 1) // size if size else 0
    return LoginHistoryResponse(
        items=[LoginHistoryItem.model_validate(item) for item in items],
        total=total,
        page=page,
        size=size,
        pages=pages,
    )
