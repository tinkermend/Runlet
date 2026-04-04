import secrets
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="AI Playwright Platform")
    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")
    json_logs: bool = Field(default=False)
    database_url: str = Field(
        default="postgresql+asyncpg://aiops:AIOps!1234@127.0.0.1:5432/runlet"
    )
    redis_url: str = Field(default="redis://127.0.0.1:6379/0")
    playwright_headless: bool = Field(default=True)
    ddddocr_enabled: bool = Field(default=True)
    scheduler_enabled: bool = Field(default=True)
    scheduler_timezone: str = Field(default="UTC")
    scheduler_reload_interval_seconds: float = Field(default=30.0, ge=0.0)
    worker_poll_interval_ms: int = Field(default=500, ge=1)
    credential_crypto_secret: str = Field(default="runlet-local-credential-secret")
    console_username: str = Field(default="admin")
    console_password: str = Field(default="admin")
    session_secret: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    session_ttl_hours: int = Field(default=8, ge=1)
    pat_max_ttl_days: int = Field(default=7, ge=1)
    pat_allowed_ttl_days: Annotated[list[int], NoDecode] = Field(default_factory=lambda: [3, 7])
    password_pepper: str | None = Field(default=None)

    @field_validator("pat_allowed_ttl_days", mode="before")
    @classmethod
    def parse_pat_allowed_ttl_days(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            parts = [part.strip() for part in value.split(",") if part.strip()]
            return [int(part) for part in parts]
        if isinstance(value, (list, tuple, set)):
            return [int(part) for part in value]
        return value

    @field_validator("pat_allowed_ttl_days")
    @classmethod
    def validate_pat_allowed_ttl_days(cls, value, info):
        if not value:
            raise ValueError("pat_allowed_ttl_days must not be empty")
        if any(item <= 0 for item in value):
            raise ValueError("pat_allowed_ttl_days must contain only positive integers")
        max_days = info.data.get("pat_max_ttl_days")
        if max_days is not None and any(item > max_days for item in value):
            raise ValueError("pat_allowed_ttl_days must be <= pat_max_ttl_days")
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
