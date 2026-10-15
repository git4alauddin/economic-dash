"""Load and validate backend environment configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIRECTORY / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    api_host: str = Field(default="127.0.0.1", min_length=1)
    api_port: int = Field(default=8000, ge=1, le=65535)
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_origins(cls, origins: list[str]) -> list[str]:
        if not origins:
            raise ValueError("At least one frontend origin must be configured.")

        for origin in origins:
            parsed = urlsplit(origin)
            if (
                "*" in origin
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
                or any(character.isspace() for character in origin)
            ):
                raise ValueError("CORS origins must be exact HTTP(S) origins without paths.")
            # Accessing port also rejects malformed or out-of-range port values.
            _ = parsed.port

        return origins

    @model_validator(mode="after")
    def validate_production_origin(self) -> Self:
        if self.app_env == "production":
            if (
                len(self.cors_allowed_origins) != 1
                or not self.cors_allowed_origins[0].startswith("https://")
            ):
                raise ValueError("Production requires exactly one HTTPS frontend origin.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
