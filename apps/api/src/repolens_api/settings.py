"""Environment-backed application settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from REPOLENS_API-prefixed variables."""

    model_config = SettingsConfigDict(
        env_prefix="REPOLENS_API_",
        case_sensitive=False,
        extra="ignore",
    )

    debug: bool = False
    database_url: str = "postgresql+asyncpg://repolens:repolens-local@localhost:5432/repolens"
    redis_url: str = "redis://localhost:6379/0"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
