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
    scheduler_enabled: bool = Field(default=True)
    scheduler_timezone: str = Field(default="UTC")
    worker_poll_interval_ms: int = Field(default=500, ge=1)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
