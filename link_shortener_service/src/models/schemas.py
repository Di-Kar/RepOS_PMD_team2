"""Pydantic-схемы HTTP API link_shortener_service (docs/link_shortener_contract.md)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

ALLOWED_REDIRECT_SCHEMES = ("http://", "https://")


class CreateLinkRequest(BaseModel):
    source_service: str = Field(..., min_length=1, max_length=50)
    owner_user_id: uuid.UUID | None = None
    purpose: str = Field(default="generic", max_length=50)
    redirect_url: str = Field(..., min_length=1)
    ttl_seconds: int | None = Field(default=None, gt=0)

    @field_validator("redirect_url")
    @classmethod
    def _validate_redirect_url(cls, value: str) -> str:
        # POST /api/v1/links — доверенный S2S-эндпоинт (X-API-Key), но
        # минимальная защита от javascript:/data: схем на входе дёшева и не
        # вредит легитимным вызовам.
        if not value.startswith(ALLOWED_REDIRECT_SCHEMES):
            raise ValueError("redirect_url must start with http:// or https://")
        return value


class CreateLinkResponse(BaseModel):
    code: str
    short_url: str
    expires_at: datetime
