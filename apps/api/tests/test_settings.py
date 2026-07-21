"""Tests for acquisition configuration validation."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from repolens_api.settings import Settings


def test_acquisition_settings_accept_consistent_positive_limits(tmp_path: Path) -> None:
    settings = Settings(
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


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
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
