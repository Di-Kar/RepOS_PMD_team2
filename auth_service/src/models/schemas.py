"""Pydantic-схемы запросов/ответов (auth — по openapi_auth.yaml, idm — по openapi_idm.yaml)."""

import uuid
from datetime import datetime
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class BaseSchema(BaseModel):
    """Base schema with common configuration."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True, use_enum_values=True)


class UserRegisterRequest(BaseSchema):
    """Запрос регистрации. Email используется как логин."""

    email: EmailStr = Field(..., min_length=5, max_length=255, description="Email (login)")
    password: str = Field(..., min_length=8, max_length=255, description="User password")
    full_name: Optional[str] = Field(None, max_length=100, description="Full name")


class UserRegisterResponse(BaseSchema):
    """Ответ на регистрацию."""

    id: uuid.UUID = Field(..., description="User ID")
    email: str = Field(..., description="Email (login)")
    full_name: str = Field(default="", description="Full name")
    created_at: datetime = Field(..., description="Account creation date")


class UserResponse(BaseSchema):
    """Профиль пользователя (GET/PUT /profile)."""

    id: uuid.UUID = Field(..., description="User ID")
    email: str = Field(..., description="Email (login)")
    full_name: str = Field(default="", description="Full name")
    roles: List[str] = Field(default_factory=list, description="Role names assigned to the user")
    is_superuser: bool = Field(default=False, description="Superuser flag")


class UserUpdateRequest(BaseSchema):
    """Запрос обновления профиля: менять можно только full_name."""

    full_name: str = Field(..., min_length=1, max_length=100, description="New full name")


class UserLoginRequest(BaseSchema):
    """Запрос входа."""

    email: EmailStr = Field(..., description="Email (login)")
    password: str = Field(..., min_length=1, description="User password")


class TokenPair(BaseSchema):
    """Пара токенов (access + refresh)."""

    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")


class RefreshRequest(BaseSchema):
    """Запрос обновления access-токена."""

    refresh_token: str = Field(..., description="JWT refresh token")


class ChangePasswordRequest(BaseSchema):
    """Запрос смены пароля."""

    current_password: str = Field(..., description="Current password")
    new_password: str = Field(..., min_length=8, description="New password")


class RoleCreate(BaseSchema):
    """Schema for role creation."""

    name: str = Field(..., min_length=3, max_length=100, description="Unique role name")
    description: Optional[str] = Field(None, description="Role description")
    permissions: List[str] = Field(default_factory=list, description="Permission strings, e.g. video:watch")


class RoleUpdate(BaseSchema):
    """Schema for role update."""

    name: Optional[str] = Field(None, min_length=3, max_length=100, description="New role name")
    description: Optional[str] = Field(None, description="New role description")
    permissions: Optional[List[str]] = Field(None, description="Permission strings, e.g. video:watch")


class RoleResponse(BaseSchema):
    """Schema for basic role response."""

    id: uuid.UUID = Field(..., description="Role ID")
    name: str = Field(..., description="Role name")
    description: Optional[str] = Field(None, description="Role description")
    permissions: List[str] = Field(default_factory=list, description="Permission strings")
    created_at: datetime = Field(..., description="Creation date")


class RoleDetailResponse(RoleResponse):
    """Schema for detailed role response."""

    updated_at: datetime = Field(..., description="Last update date")


class RolesListResponse(BaseSchema):
    """Schema for roles list response."""

    items: List[RoleResponse] = Field(..., description="List of roles")
    total: int = Field(..., description="Total number of roles")


class UserRoleRequest(BaseSchema):
    """Schema for assigning a role to a user."""

    role_id: uuid.UUID = Field(..., description="Role ID to assign")


class LoginHistoryItem(BaseSchema):
    """Запись истории входов. В спеке поле называется timestamp, в БД — login_at."""

    id: uuid.UUID = Field(..., description="History record ID")
    user_agent: Optional[str] = Field(None, description="User agent")
    ip_address: Optional[str] = Field(None, description="IP address")
    fingerprint: Optional[str] = Field(None, description="Device fingerprint")
    timestamp: datetime = Field(..., validation_alias="login_at", description="Login timestamp")
    success: bool = Field(..., description="Login success status")


class LoginHistoryResponse(BaseSchema):
    """Schema for paginated login history response."""

    items: List[LoginHistoryItem] = Field(..., description="History items")
    total: int = Field(..., description="Total records")
    page: int = Field(..., description="Current page")
    size: int = Field(..., description="Page size")
    pages: int = Field(..., description="Total pages")


class PermissionCheckRequest(BaseSchema):
    """Schema for permission check request."""

    permission: str = Field(..., min_length=3, max_length=100, description="Permission to check, e.g. video:delete")


class PermissionCheckResponse(BaseSchema):
    """Schema for permission check response."""

    has_permission: bool = Field(..., description="Whether the requested permission is granted")
    granted_permissions: List[str] = Field(default_factory=list, description="All permissions the user has")
    missing_permissions: List[str] = Field(
        default_factory=list, description="Requested permissions the user lacks"
    )


class MessageResponse(BaseSchema):
    """Schema for generic message response."""

    message: str = Field(..., description="Message text")


class ErrorResponse(BaseSchema):
    """Schema for error response."""

    detail: str = Field(..., description="Error description")
    error_code: str = Field(..., description="Error code")
    timestamp: datetime = Field(..., description="Error timestamp")


class DependencyStatus(BaseSchema):
    """Schema for dependency status."""

    postgres: str = Field(..., description="PostgreSQL status")
    redis: str = Field(..., description="Redis status")


class HealthCheckResponse(BaseSchema):
    """Schema for health check response."""

    status: str = Field(..., description="Service status")
    timestamp: datetime = Field(..., description="Check timestamp")
    version: str = Field(..., description="Service version")
    dependencies: DependencyStatus = Field(..., description="Dependencies status")


T = TypeVar("T")


class PaginatedResponse(BaseSchema, Generic[T]):
    """Generic schema for paginated responses."""

    items: List[T] = Field(..., description="List of items")
    total: int = Field(..., description="Total items count")
    page: int = Field(..., description="Current page number")
    size: int = Field(..., description="Items per page")
    pages: int = Field(..., description="Total pages count")

    @classmethod
    def create(cls, items: List[T], total: int, page: int, size: int) -> "PaginatedResponse[T]":
        """Create paginated response with calculated pages."""
        pages = (total + size - 1) // size if size > 0 else 0
        return cls(items=items, total=total, page=page, size=size, pages=pages)


class TokenPayload(BaseSchema):
    """Полезная нагрузка JWT-токена."""

    sub: str = Field(..., description="Subject (user_id)")
    login: Optional[str] = Field(None, description="User login (email)")
    roles: Optional[List[str]] = Field(None, description="User role names")
    is_superuser: bool = Field(False, description="Superuser flag")
    token_type: str = Field(..., description="Token type (access/refresh)")
    jti: str = Field(..., description="JWT ID")
    session_id: str = Field(..., description="Session ID (общий у access и refresh пары)")
    exp: int = Field(..., description="Expiration timestamp")
    iat: int = Field(..., description="Issued at timestamp")
