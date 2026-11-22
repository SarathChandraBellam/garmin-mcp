"""Runtime settings, read from environment variables (and an optional ``.env``)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All knobs the server understands. None of them is required for local use."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    public_base_url: str | None = Field(
        default=None,
        validation_alias="PUBLIC_BASE_URL",
        description="Public origin shown on the landing page; defaults to the request's origin.",
    )
    default_timezone: str = Field(default="UTC", validation_alias="DEFAULT_TIMEZONE")
    allow_insecure_http: bool = Field(default=False, validation_alias="ALLOW_INSECURE_HTTP")
    garmin_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="GARMIN_API_KEY",
        description="Key used in stdio mode only.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
