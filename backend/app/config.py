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


class DatabaseSettings(BaseSettings):
    """Dedicated private directory; Render must mount /var/data before startup."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIRECTORY / ".env", env_file_encoding="utf-8",
        env_prefix="DATABASE_", extra="ignore", allow_inf_nan=False,
    )

    app_env: Literal["development", "test", "production"] = "development"
    directory: Path | None = None
    busy_timeout: float = Field(default=5, gt=0, le=30)
    max_connections: int = Field(default=8, ge=1, le=32)
    read_timeout: float = Field(default=2, gt=0, le=10)

    @model_validator(mode="after")
    def validate_directory(self) -> Self:
        directory = self.directory
        if directory is None:
            directory = (Path("/var/data/economic-dash") if self.app_env == "production"
                         else BACKEND_DIRECTORY / ".runtime" / "database")
        directory = directory.expanduser()
        if not directory.is_absolute():
            directory = BACKEND_DIRECTORY / directory
        directory = directory.resolve()
        frontend = BACKEND_DIRECTORY.parent / "frontend"
        shared_directories = {
            Path(directory.anchor), BACKEND_DIRECTORY,
            BACKEND_DIRECTORY.parent, Path("/var/data").resolve(),
        }
        try:
            shared_directories.add(Path.home())
        except RuntimeError:
            pass  # Minimal service/test environments may have no home directory.
        if directory.is_relative_to(frontend) or directory in shared_directories:
            raise ValueError("Database requires a dedicated directory outside frontend assets.")
        if self.app_env == "production" and not directory.is_relative_to(Path("/var/data").resolve()):
            raise ValueError("Production database must be beneath the /var/data persistent mount.")
        self.directory = directory
        return self

    @property
    def path(self) -> Path:
        assert self.directory is not None
        return self.directory / "dashboard.sqlite3"


def get_database_settings(app_env: str) -> DatabaseSettings:
    return DatabaseSettings(app_env=app_env)


class CollectorSettings(BaseSettings):
    """Acquisition limits; scheduling and observation freshness are separate."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIRECTORY / ".env", env_file_encoding="utf-8",
        env_prefix="COLLECTOR_", extra="ignore", allow_inf_nan=False,
    )

    user_agent: str = Field(default="EconomicDashboard/0.1 source-collector", min_length=8, max_length=256)
    connect_timeout: float = Field(default=5, gt=0, le=30)
    read_timeout: float = Field(default=10, gt=0, le=60)
    attempt_timeout: float = Field(default=15, gt=0, le=120)
    total_timeout: float = Field(default=45, gt=0, le=180)
    max_attempts: int = Field(default=3, ge=1, le=5)
    min_interval: float = Field(default=1, gt=0, le=60)
    backoff_base: float = Field(default=0.5, gt=0, le=10)
    backoff_cap: float = Field(default=5, gt=0, le=30)
    max_connections: int = Field(default=4, ge=1, le=8)
    max_bytes: int = Field(default=2_000_000, ge=1, le=25_000_000)

    @field_validator("user_agent")
    @classmethod
    def validate_user_agent(cls, value: str) -> str:
        if any(ord(char) < 32 or ord(char) > 126 for char in value):
            raise ValueError("Collector User-Agent must contain printable ASCII only.")
        return value

    @model_validator(mode="after")
    def validate_budgets(self) -> Self:
        if self.backoff_base > self.backoff_cap:
            raise ValueError("Backoff base cannot exceed its cap.")
        if self.attempt_timeout > self.total_timeout:
            raise ValueError("Attempt timeout cannot exceed total acquisition timeout.")
        return self


class SchedulerSettings(BaseSettings):
    """One lifespan owner; use a shared persistent directory on the production host."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIRECTORY / ".env", env_file_encoding="utf-8",
        env_prefix="COLLECTOR_SCHEDULER_", extra="ignore", allow_inf_nan=False,
    )

    enabled: bool = True
    state_directory: Path = BACKEND_DIRECTORY / ".runtime"
    startup_delay: float = Field(default=1, ge=0, le=60)
    tick_seconds: float = Field(default=30, gt=0, le=300)
    run_timeout: float = Field(default=300, gt=0, le=1800)
    shutdown_timeout: float = Field(default=10, gt=0, le=60)
    discovery_limit: int = Field(default=2, ge=1, le=4)

    @field_validator("state_directory")
    @classmethod
    def absolute_directory(cls, value: Path) -> Path:
        return value.expanduser().resolve()


def get_scheduler_settings(app_env: str) -> SchedulerSettings:
    settings = SchedulerSettings()
    if app_env == "production" and "state_directory" not in settings.model_fields_set:
        settings = SchedulerSettings(state_directory=Path("/var/data/economic-dash"))
    return settings
