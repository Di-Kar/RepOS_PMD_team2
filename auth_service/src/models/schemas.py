"""Pydantic schemas for request/response validation."""

import uuid
from datetime import datetime
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field, ConfigDict


class BaseSchema(BaseModel):
    """Base schema with common configuration."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True, use_enum_values=True)


class UserCreate(BaseSchema):
    """Schema for user registration."""

    login: str = Field(..., min_length=3, max_length=255, description="Unique login")
    password: str = Field(..., min_length=8, max_length=255, description="User password")
    first_name: str = Field(..., max_length=50, description="First name")
    last_name: str = Field(..., max_length=50, description="Last name")


class UserResponse(BaseSchema):
    """Schema for basic user response."""

    id: uuid.UUID = Field(..., description="User ID")
    login: str = Field(..., description="User login")
    first_name: str = Field(..., description="First name")
    last_name: str = Field(..., description="Last name")
    created_at: datetime = Field(..., description="Account creation date")


class UserDetailResponse(UserResponse):
    """Schema for detailed user response with roles."""

    is_superuser: bool = Field(..., description="Is user a superuser")
    roles: List["RoleResponse"] = Field(default_factory=list, description="User roles")


class LoginRequest(BaseSchema):
    """Schema for login request."""

    login: str = Field(..., description="User login")
    password: str = Field(..., description="User password")


class TokenResponse(BaseSchema):
    """Schema for token response (access + refresh)."""

    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")


class AccessTokenResponse(BaseSchema):
    """Schema for access token only response."""

    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")


class RefreshRequest(BaseSchema):
    """Schema for refresh token request."""

    refresh_token: str = Field(..., description="JWT refresh token")


class ChangePasswordRequest(BaseSchema):
    """Schema for password change request."""

    old_password: str = Field(..., description="Current password")
    new_password: str = Field(..., min_length=8, description="New password")


class RoleCreate(BaseSchema):
    """Schema for role creation."""

    name: str = Field(..., max_length=100, description="Unique role name")
    description: Optional[str] = Field(None, description="Role description")


class RoleUpdate(BaseSchema):
    """Schema for role update."""

    name: Optional[str] = Field(None, max_length=100, description="New role name")
    description: Optional[str] = Field(None, description="New role description")


class RoleResponse(BaseSchema):
    """Schema for basic role response."""

    id: uuid.UUID = Field(..., description="Role ID")
    name: str = Field(..., description="Role name")
    description: Optional[str] = Field(None, description="Role description")
    created_at: datetime = Field(..., description="Creation date")


class RoleDetailResponse(RoleResponse):
    """Schema for detailed role response."""

    updated_at: datetime = Field(..., description="Last update date")


class RolesListResponse(BaseSchema):
    """Schema for roles list response."""

    items: List[RoleResponse] = Field(..., description="List of roles")
    total: int = Field(..., description="Total number of roles")


class RoleAssignmentResponse(BaseSchema):
    """Schema for role assignment response."""

    message: str = Field(..., description="Result message")
    user_id: uuid.UUID = Field(..., description="User ID")
    role_id: uuid.UUID = Field(..., description="Role ID")


class LoginHistoryItem(BaseSchema):
    """Schema for login history item."""

    id: uuid.UUID = Field(..., description="History record ID")
    user_agent: Optional[str] = Field(None, description="User agent")
    ip_address: Optional[str] = Field(None, description="IP address")
    fingerprint: Optional[str] = Field(None, description="Device fingerprint")
    login_at: datetime = Field(..., description="Login timestamp")
    success: bool = Field(..., description="Login success status")


class LoginHistoryResponse(BaseSchema):
    """Schema for paginated login history response."""

    items: List[LoginHistoryItem] = Field(..., description="History items")
    total: int = Field(..., description="Total records")
    page: int = Field(..., description="Current page")
    size: int = Field(..., description="Page size")
    pages: int = Field(..., description="Total pages")


class PermissionCheckResponse(BaseSchema):
    """Schema for permission check response."""

    has_permission: bool = Field(..., description="Permission status")
    user_id: uuid.UUID = Field(..., description="User ID")
    role: str = Field(..., description="Checked role")


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


class UserInDB(BaseSchema):
    """Internal user schema with password hash."""

    id: uuid.UUID
    login: str
    password: str  # Hashed password
    first_name: str
    last_name: str
    is_active: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime


class TokenPayload(BaseSchema):
    """Schema for JWT token payload."""

    sub: str = Field(..., description="Subject (user_id)")
    login: Optional[str] = Field(None, description="User login")
    roles: Optional[List[str]] = Field(None, description="User roles")
    token_type: str = Field(..., description="Token type (access/refresh)")
    jti: str = Field(..., description="JWT ID")
    version: Optional[int] = Field(None, description="Token version")
    exp: int = Field(..., description="Expiration timestamp")
    iat: int = Field(..., description="Issued at timestamp")


class UserWithRoles(BaseSchema):
    """Internal schema for user with role names."""

    id: uuid.UUID
    login: str
    first_name: str
    last_name: str
    is_active: bool
    is_superuser: bool
    roles: List[str] = Field(default_factory=list, description="Role names")
    created_at: datetime


# Update forward references
UserDetailResponse.model_rebuild()
