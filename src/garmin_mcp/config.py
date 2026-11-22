"""Runtime settings, read from environment variables (and an optional ``.env``)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All knobs the server understands. None of them is required for local use."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    public_base_url: str = Field(
        default="http://localhost:8000",
        validation_alias="PUBLIC_BASE_URL",
        description="Public origin of this deployment; used in OAuth metadata and the landing page.",
    )
    secret_key: SecretStr | None = Field(
        default=None,
        validation_alias="GARMIN_MCP_SECRET",
        description=(
            "Server secret that seals OAuth client ids, codes and tokens. Required when more "
            "than one instance serves traffic or tokens must survive restarts."
        ),
    )
    default_timezone: str = Field(default="UTC", validation_alias="DEFAULT_TIMEZONE")
    allow_insecure_http: bool = Field(default=False, validation_alias="ALLOW_INSECURE_HTTP")
    garmin_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="GARMIN_API_KEY",
        description="Key used in stdio mode only.",
    )
    access_token_ttl: int = Field(default=3600, validation_alias="ACCESS_TOKEN_TTL_SECONDS")
    refresh_token_ttl: int = Field(
        default=30 * 86_400, validation_alias="REFRESH_TOKEN_TTL_SECONDS"
    )

    @property
    def base_url(self) -> str:
        return self.public_base_url.rstrip("/")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
