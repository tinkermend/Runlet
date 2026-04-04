import secrets

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, EnvSettingsSource, SettingsConfigDict


class PatEnvSettingsSource(EnvSettingsSource):
    def prepare_field_value(self, field_name, field, value, value_is_complex):
        if field_name == "pat_allowed_ttl_days" and isinstance(value, str):
            parts = [part.strip() for part in value.split(",") if part.strip()]
            return parts
        return super().prepare_field_value(field_name, field, value, value_is_complex)


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
    session_secret: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    session_ttl_hours: int = Field(default=8, ge=1)
    pat_max_ttl_days: int = Field(default=7, ge=1)
    pat_allowed_ttl_days: list[int] = Field(default_factory=lambda: [3, 7])
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

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (
            init_settings,
            PatEnvSettingsSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_parse_delimiter=",",
        case_sensitive=False,
    )


settings = Settings()
