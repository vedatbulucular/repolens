"""Tests for acquisition configuration validation."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from repolens_api.settings import Settings


def test_acquisition_settings_accept_consistent_positive_limits(tmp_path: Path) -> None:
    settings = Settings(
        broker_visibility_timeout_seconds=30,
        acquisition_timeout_seconds=1,
        max_repository_bytes=10,
        max_workspace_bytes=20,
        max_file_count=2,
        max_file_bytes=5,
        max_path_length=10,
        max_path_depth=2,
        workspace_root=tmp_path.resolve(),
        inventory_timeout_seconds=1,
        max_inventory_entries=2,
        max_inventory_directories=1,
        max_inventory_path_length=10,
        max_manifest_bytes=4,
        max_text_read_bytes=3,
        binary_sample_bytes=2,
        max_analysis_warnings=1,
        max_json_nesting_depth=3,
        max_manifest_nodes=10,
        max_technology_findings=4,
        max_technology_evidence_per_finding=2,
        max_entry_points=3,
    )

    assert settings.acquisition_limits().max_workspace_bytes == 20
    assert settings.broker_visibility_timeout_seconds == 30
    assert settings.inventory_limits().max_entries == 2
    assert settings.inventory_limits().binary_sample_bytes == 2
    assert settings.inventory_limits().max_manifest_nodes == 10


def test_broker_visibility_timeout_loads_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPOLENS_API_BROKER_VISIBILITY_TIMEOUT_SECONDS", "45")

    assert Settings().broker_visibility_timeout_seconds == 45


def test_compose_worker_concurrency_uses_one_documented_setting() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    compose = (repository_root / "compose.yaml").read_text(encoding="utf-8")
    environment_example = (repository_root / ".env.example").read_text(encoding="utf-8")

    compose_setting = '"${REPOLENS_WORKER_CONCURRENCY:-2}"'
    assert compose.count(compose_setting) == 1
    assert "REPOLENS_WORKER_CONCURRENCY=2" in environment_example


def test_inventory_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPOLENS_API_INVENTORY_TIMEOUT_SECONDS", "11")
    monkeypatch.setenv("REPOLENS_API_MAX_ANALYSIS_WARNINGS", "17")
    monkeypatch.setenv("REPOLENS_API_MAX_ENTRY_POINTS", "19")

    limits = Settings().inventory_limits()

    assert limits.timeout_seconds == 11
    assert limits.max_warnings == 17
    assert limits.max_entry_points == 19


def test_inventory_settings_are_documented_and_passed_only_to_worker() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    compose = (repository_root / "compose.yaml").read_text(encoding="utf-8")
    environment_example = (repository_root / ".env.example").read_text(encoding="utf-8")
    names = (
        "REPOLENS_API_INVENTORY_TIMEOUT_SECONDS",
        "REPOLENS_API_MAX_INVENTORY_ENTRIES",
        "REPOLENS_API_MAX_INVENTORY_DIRECTORIES",
        "REPOLENS_API_MAX_INVENTORY_PATH_LENGTH",
        "REPOLENS_API_MAX_MANIFEST_BYTES",
        "REPOLENS_API_MAX_TEXT_READ_BYTES",
        "REPOLENS_API_BINARY_SAMPLE_BYTES",
        "REPOLENS_API_MAX_ANALYSIS_WARNINGS",
        "REPOLENS_API_MAX_JSON_NESTING_DEPTH",
        "REPOLENS_API_MAX_MANIFEST_NODES",
        "REPOLENS_API_MAX_TECHNOLOGY_FINDINGS",
        "REPOLENS_API_MAX_TECHNOLOGY_EVIDENCE_PER_FINDING",
        "REPOLENS_API_MAX_ENTRY_POINTS",
    )

    for name in names:
        assert f"{name}=" in environment_example
        assert sum(line.lstrip().startswith(f"{name}:") for line in compose.splitlines()) == 1


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        (
            {"broker_visibility_timeout_seconds": 0},
            "broker visibility timeout must be positive",
        ),
        ({"acquisition_timeout_seconds": 0}, "must be positive"),
        (
            {"max_file_bytes": 11, "max_repository_bytes": 10},
            "max file bytes cannot exceed max repository bytes",
        ),
        (
            {"max_repository_bytes": 21, "max_workspace_bytes": 20},
            "max repository bytes cannot exceed max workspace bytes",
        ),
        ({"workspace_root": Path("relative")}, "workspace root must be an absolute path"),
        ({"inventory_timeout_seconds": 0}, "inventory limits must be positive"),
        (
            {"max_inventory_entries": 3},
            "inventory entry limit cannot exceed acquisition entry limit",
        ),
        (
            {"max_inventory_directories": 3},
            "inventory directory limit cannot exceed inventory entry limit",
        ),
        (
            {"max_inventory_path_length": 11},
            "inventory path limit cannot exceed acquisition path limit",
        ),
        (
            {"max_manifest_bytes": 6},
            "manifest read limit cannot exceed acquisition file limit",
        ),
        (
            {"max_text_read_bytes": 6},
            "text read limit cannot exceed acquisition file limit",
        ),
        (
            {"binary_sample_bytes": 4},
            "binary sample limit cannot exceed text read limit",
        ),
        ({"max_json_nesting_depth": 0}, "inventory limits must be positive"),
        ({"max_manifest_nodes": 0}, "inventory limits must be positive"),
        ({"max_technology_findings": 0}, "inventory limits must be positive"),
        (
            {"max_technology_evidence_per_finding": 0},
            "inventory limits must be positive",
        ),
        ({"max_entry_points": 0}, "inventory limits must be positive"),
    ],
)
def test_acquisition_settings_reject_unsafe_values(
    tmp_path: Path,
    overrides: dict[str, object],
    expected_message: str,
) -> None:
    values: dict[str, object] = {
        "broker_visibility_timeout_seconds": 30,
        "acquisition_timeout_seconds": 1,
        "max_repository_bytes": 10,
        "max_workspace_bytes": 20,
        "max_file_count": 2,
        "max_file_bytes": 5,
        "max_path_length": 10,
        "max_path_depth": 2,
        "workspace_root": tmp_path.resolve(),
        "inventory_timeout_seconds": 1,
        "max_inventory_entries": 2,
        "max_inventory_directories": 1,
        "max_inventory_path_length": 10,
        "max_manifest_bytes": 4,
        "max_text_read_bytes": 3,
        "binary_sample_bytes": 2,
        "max_analysis_warnings": 1,
        "max_json_nesting_depth": 3,
        "max_manifest_nodes": 10,
        "max_technology_findings": 4,
        "max_technology_evidence_per_finding": 2,
        "max_entry_points": 3,
    }
    values.update(overrides)

    with pytest.raises(ValidationError, match=expected_message):
        Settings.model_validate(values)
