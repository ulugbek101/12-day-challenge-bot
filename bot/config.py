"""Application configuration, loaded once from environment variables / .env.

Everything sensitive or environment-specific lives here and nowhere else
(no secrets in code, Dockerfile, docker-compose.yml or alembic.ini).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """Raised when .env is missing a required value or a value is malformed.

    Meant to fail the process fast and loud at startup, before polling begins.
    """


def parse_admins(raw: str) -> list[int]:
    """Parse the comma-separated ADMINS env value into a list of Telegram ids.

    Tolerates surrounding/inner spaces and trailing commas. Raises ConfigError
    with a specific, actionable message on anything else malformed or empty.
    """
    raw = (raw or "").strip()
    if not raw:
        raise ConfigError(
            "ADMINS is empty. Set at least one admin Telegram id, e.g. ADMINS=123456789"
        )

    admins: list[int] = []
    for chunk in raw.split(","):
        token = chunk.strip()
        if not token:
            continue
        if not token.lstrip("-").isdigit():
            raise ConfigError(
                f"ADMINS contains a non-numeric value: {token!r}. "
                "Expected comma-separated Telegram ids, e.g. ADMINS=123456789,987654321"
            )
        admins.append(int(token))

    if not admins:
        raise ConfigError(
            "ADMINS is empty. Set at least one admin Telegram id, e.g. ADMINS=123456789"
        )
    return admins


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    bot_token: str = Field(alias="BOT_TOKEN")
    admins: list[int] = Field(alias="ADMINS")
    channel_id: int = Field(alias="CHANNEL_ID")

    db_host: str = Field(alias="DB_HOST")
    db_port: int = Field(default=3306, alias="DB_PORT")
    db_user: str = Field(alias="DB_USER")
    db_password: str = Field(alias="DB_PASSWORD")
    db_name: str = Field(alias="DB_NAME")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    tz: str = Field(default="UTC", alias="TZ")
    default_language: str = Field(default="ru", alias="DEFAULT_LANGUAGE")
    payment_page_url: str = Field(alias="PAYMENT_PAGE_URL")
    support_username: str = Field(default="", alias="SUPPORT_USERNAME")
    invite_link_ttl_hours: int = Field(default=24, alias="INVITE_LINK_TTL_HOURS")
    reminder_before_expiry_hours: int = Field(default=6, alias="REMINDER_BEFORE_EXPIRY_HOURS")

    @field_validator("admins", mode="before")
    @classmethod
    def _parse_admins(cls, value: object) -> list[int]:
        if isinstance(value, list):
            return value  # type: ignore[return-value]
        return parse_admins(str(value))

    @field_validator("default_language")
    @classmethod
    def _validate_default_language(cls, value: str) -> str:
        if value not in ("ru", "uz"):
            raise ConfigError(f"DEFAULT_LANGUAGE must be 'ru' or 'uz', got {value!r}")
        return value

    @property
    def database_url(self) -> str:
        """Async SQLAlchemy URL using the asyncmy driver, utf8mb4 charset."""
        return (
            f"mysql+asyncmy://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )


def load_settings() -> Settings:
    try:
        return Settings()
    except ConfigError:
        raise
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration: {exc}") from exc


settings = load_settings()
