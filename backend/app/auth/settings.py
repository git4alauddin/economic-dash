"""Server-only token policy; there is no default signing key."""

import re
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import BACKEND_DIRECTORY


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIRECTORY / ".env", env_file_encoding="utf-8",
        env_prefix="AUTH_", extra="ignore", hide_input_in_errors=True)

    app_env: Literal["development", "test", "production"] = "development"
    jwt_signing_key: SecretStr | None = Field(default=None, repr=False, exclude=True)
    jwt_issuer: str = Field(default="economic-dash-api", min_length=1, max_length=100)
    jwt_audience: str = Field(default="economic-dash-web", min_length=1, max_length=100)
    access_token_minutes: int = Field(default=15, ge=5, le=30)
    clock_skew_seconds: int = Field(default=5, ge=0, le=30)
    login_client_attempts: int = Field(default=10, ge=1, le=100)
    login_global_attempts: int = Field(default=60, ge=1, le=1000)
    login_window_seconds: int = Field(default=60, ge=1, le=3600)
    login_max_clients: int = Field(default=1024, ge=1, le=10000)

    @field_validator("jwt_signing_key")
    @classmethod
    def validate_key(cls, value):
        if value is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", value.get_secret_value()):
            raise ValueError("AUTH_JWT_SIGNING_KEY must be 32 random bytes encoded as 64 hex characters.")
        return value

    @field_validator("jwt_issuer", "jwt_audience")
    @classmethod
    def validate_identifier(cls, value):
        if not re.fullmatch(r"[!-~]+", value):
            raise ValueError("Token issuer/audience must contain printable ASCII without spaces.")
        return value

    @model_validator(mode="after")
    def production_key_required(self) -> Self:
        if self.app_env == "production" and self.jwt_signing_key is None:
            raise ValueError("Production requires AUTH_JWT_SIGNING_KEY.")
        return self
