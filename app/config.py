"""Application settings, loaded from the environment only.

No secret has a usable default. If SECRET_KEY is missing in production the app
refuses to start rather than falling back to something guessable — a default
signing key in a public repo is how sessions get forged.
"""

from __future__ import annotations

import secrets
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Bharti"
    environment: str = Field(default="development", alias="ENVIRONMENT")
    debug: bool = Field(default=False, alias="DEBUG")

    secret_key: str = Field(default="", alias="SECRET_KEY")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(
        default=60 * 12, alias="ACCESS_TOKEN_EXPIRE_MINUTES"
    )

    database_url: str = Field(default="sqlite:///./bharti.db", alias="DATABASE_URL")

    cors_origins: str = Field(
        default="http://localhost:8000,http://127.0.0.1:8000", alias="CORS_ORIGINS"
    )

    rate_limit_auth: str = Field(default="10/minute", alias="RATE_LIMIT_AUTH")
    rate_limit_default: str = Field(default="120/minute", alias="RATE_LIMIT_DEFAULT")

    #: Opt-in only. On a public deployment the first stranger to sign up would
    #: otherwise become the platform administrator.
    first_user_is_admin: bool = Field(default=False, alias="FIRST_USER_IS_ADMIN")

    @field_validator("secret_key")
    @classmethod
    def _check_secret(cls, value: str) -> str:
        if value:
            return value
        # Development convenience: generate an ephemeral key so `uvicorn
        # app.main:app` works out of the box. Tokens do not survive a restart,
        # which is the correct behaviour for a throwaway key.
        return secrets.token_urlsafe(48)

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in ("production", "prod")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.is_production and not settings.secret_key:
        raise RuntimeError(
            "SECRET_KEY must be set in production. Generate one with: "
            'python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    return settings
