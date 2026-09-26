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
    # Kept as a plain str field (not list[int]) because pydantic-settings tries to
    # JSON-decode "complex" env values before any validator runs, which breaks on a
    # plain CSV string like "123,456". Parsing happens in the `admins` property below.
    admins_raw: str = Field(alias="ADMINS")
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

    @property
    def admins(self) -> list[int]:
        return parse_admins(self.admins_raw)

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


@lru_cache
def get_settings() -> Settings:
    """Build (and cache) the Settings singleton. Call this, don't instantiate Settings directly.

    Deliberately not evaluated at import time: importing bot.config must not require a
    live .env (tests, tooling). The one required fail-fast call site is bot/__main__.py,
    which calls this before anything else happens, and also eagerly touches `.admins` so
    a malformed ADMINS value aborts startup immediately rather than on first use.
    """
    try:
        settings = Settings()
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration: {exc}") from exc
    _ = settings.admins  # fail fast on a malformed ADMINS value too
    return settings
