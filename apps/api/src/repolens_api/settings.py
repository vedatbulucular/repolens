"""Environment-backed application settings."""

from functools import lru_cache
from pathlib import Path
from tempfile import gettempdir

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from repolens_api.acquisition.contracts import AcquisitionLimits
from repolens_api.inventory.contracts import InventoryLimits


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
    broker_visibility_timeout_seconds: int = 300
    acquisition_timeout_seconds: int = 60
    max_repository_bytes: int = 104_857_600
    max_workspace_bytes: int = 268_435_456
    max_file_count: int = 20_000
    max_file_bytes: int = 5_242_880
    max_path_length: int = 512
    max_path_depth: int = 40
    workspace_root: Path = Path(gettempdir()) / "repolens-workspaces"
    inventory_timeout_seconds: int = 20
    max_inventory_entries: int = 20_000
    max_inventory_directories: int = 5_000
    max_inventory_path_length: int = 512
    max_manifest_bytes: int = 1_048_576
    max_text_read_bytes: int = 262_144
    binary_sample_bytes: int = 8_192
    max_analysis_warnings: int = 200
    max_json_nesting_depth: int = 32
    max_manifest_nodes: int = 50_000
    max_technology_findings: int = 100
    max_technology_evidence_per_finding: int = 20
    max_entry_points: int = 100
    max_result_bytes: int = 2_097_152

    @model_validator(mode="after")
    def validate_acquisition_settings(self) -> "Settings":
        """Reject unsafe or internally inconsistent acquisition limits."""
        if self.broker_visibility_timeout_seconds <= 0:
            raise ValueError("broker visibility timeout must be positive")
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

        inventory_limits = (
            self.inventory_timeout_seconds,
            self.max_inventory_entries,
            self.max_inventory_directories,
            self.max_inventory_path_length,
            self.max_manifest_bytes,
            self.max_text_read_bytes,
            self.binary_sample_bytes,
            self.max_analysis_warnings,
            self.max_json_nesting_depth,
            self.max_manifest_nodes,
            self.max_technology_findings,
            self.max_technology_evidence_per_finding,
            self.max_entry_points,
        )
        if any(limit <= 0 for limit in inventory_limits):
            raise ValueError("inventory limits must be positive")
        if self.max_inventory_entries > self.max_file_count:
            raise ValueError("inventory entry limit cannot exceed acquisition entry limit")
        if self.max_inventory_directories > self.max_inventory_entries:
            raise ValueError("inventory directory limit cannot exceed inventory entry limit")
        if self.max_inventory_path_length > self.max_path_length:
            raise ValueError("inventory path limit cannot exceed acquisition path limit")
        if self.max_manifest_bytes > self.max_file_bytes:
            raise ValueError("manifest read limit cannot exceed acquisition file limit")
        if self.max_text_read_bytes > self.max_file_bytes:
            raise ValueError("text read limit cannot exceed acquisition file limit")
        if self.binary_sample_bytes > self.max_text_read_bytes:
            raise ValueError("binary sample limit cannot exceed text read limit")
        if self.max_result_bytes <= 0:
            raise ValueError("result byte limit must be positive")
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

    def inventory_limits(self) -> InventoryLimits:
        """Return the immutable limits used by repository inventory services."""
        return InventoryLimits(
            timeout_seconds=self.inventory_timeout_seconds,
            max_entries=self.max_inventory_entries,
            max_directories=self.max_inventory_directories,
            max_path_length=self.max_inventory_path_length,
            max_manifest_bytes=self.max_manifest_bytes,
            max_text_read_bytes=self.max_text_read_bytes,
            binary_sample_bytes=self.binary_sample_bytes,
            max_warnings=self.max_analysis_warnings,
            max_json_nesting_depth=self.max_json_nesting_depth,
            max_manifest_nodes=self.max_manifest_nodes,
            max_technology_findings=self.max_technology_findings,
            max_technology_evidence_per_finding=self.max_technology_evidence_per_finding,
            max_entry_points=self.max_entry_points,
        )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
