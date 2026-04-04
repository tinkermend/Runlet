from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="AI Playwright Platform")
    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")
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
    session_secret: str = Field(default="runlet-dev-session-secret")
    session_ttl_hours: int = Field(default=8, ge=1)
    pat_max_ttl_days: int = Field(default=7, ge=1)
    pat_allowed_ttl_days: list[int] = Field(default_factory=lambda: [3, 7])
    password_pepper: str | None = Field(default=None)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
