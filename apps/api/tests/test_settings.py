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
    )

    assert settings.acquisition_limits().max_workspace_bytes == 20
    assert settings.broker_visibility_timeout_seconds == 30


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
    }
    values.update(overrides)

    with pytest.raises(ValidationError, match=expected_message):
        Settings.model_validate(values)
