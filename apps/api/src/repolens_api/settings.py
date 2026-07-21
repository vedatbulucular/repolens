"""Environment-backed application settings."""

from functools import lru_cache
from pathlib import Path
from tempfile import gettempdir

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from repolens_api.acquisition.contracts import AcquisitionLimits


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
    acquisition_timeout_seconds: int = 60
    max_repository_bytes: int = 104_857_600
    max_workspace_bytes: int = 268_435_456
    max_file_count: int = 20_000
    max_file_bytes: int = 5_242_880
    max_path_length: int = 512
    max_path_depth: int = 40
    workspace_root: Path = Path(gettempdir()) / "repolens-workspaces"

    @model_validator(mode="after")
    def validate_acquisition_settings(self) -> "Settings":
        """Reject unsafe or internally inconsistent acquisition limits."""
        positive_limits = (
            self.acquisition_timeout_seconds,
            self.max_repository_bytes,
            self.max_workspace_bytes,
            self.max_file_count,
            self.max_file_bytes,
            self.max_path_length,
            self.max_path_depth,
        )
        if any(limit <= 0 for limit in positive_limits):
            raise ValueError("acquisition limits must be positive")
        if self.max_file_bytes > self.max_repository_bytes:
            raise ValueError("max file bytes cannot exceed max repository bytes")
        if self.max_repository_bytes > self.max_workspace_bytes:
            raise ValueError("max repository bytes cannot exceed max workspace bytes")
        if not self.workspace_root.is_absolute():
            raise ValueError("workspace root must be an absolute path")
        return self

    def acquisition_limits(self) -> AcquisitionLimits:
        """Return the immutable limit contract used by acquisition services."""
        return AcquisitionLimits(
            timeout_seconds=self.acquisition_timeout_seconds,
            max_repository_bytes=self.max_repository_bytes,
            max_workspace_bytes=self.max_workspace_bytes,
            max_file_count=self.max_file_count,
            max_file_bytes=self.max_file_bytes,
            max_path_length=self.max_path_length,
            max_path_depth=self.max_path_depth,
        )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
