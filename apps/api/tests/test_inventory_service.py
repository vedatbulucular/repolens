"""Integration tests for deterministic inventory orchestration."""

import json
from dataclasses import fields, replace
from pathlib import Path

import pytest

from repolens_api.inventory.content import (
    BinaryInspection,
    SafeContentReader,
    TextReadResult,
)
from repolens_api.inventory.contracts import (
    ContentStatus,
    InventoryLimits,
    InventoryResult,
    InventoryWarning,
    InventoryWarningCode,
)
from repolens_api.inventory.errors import InventoryLimitExceeded, RepositoryAnalysisFailed
from repolens_api.inventory.service import InventoryService


class DuplicateWarningReader(SafeContentReader):
    """Return the same warning from binary and shebang reads."""

    @staticmethod
    def _duplicate(relative_path: str) -> InventoryWarning:
        return InventoryWarning(
            code=InventoryWarningCode.FILE_UNREADABLE,
            relative_path=relative_path,
            message="The file content could not be read safely.",
        )

    def inspect_binary(
        self,
        repository_root: Path,
        relative_path: str,
        *,
        expected_size: int,
    ) -> BinaryInspection:
        return BinaryInspection(
            False,
            ContentStatus.AVAILABLE,
            self._duplicate(relative_path),
        )

    def read_text(
        self,
        repository_root: Path,
        relative_path: str,
        *,
        expected_size: int,
        max_bytes: int | None = None,
    ) -> TextReadResult:
        return TextReadResult(
            None,
            ContentStatus.UNREADABLE,
            self._duplicate(relative_path),
        )


class UnreadableContentReader(SafeContentReader):
    """Make one fixture path unreadable without OS permission assumptions."""

    def inspect_binary(
        self,
        repository_root: Path,
        relative_path: str,
        *,
        expected_size: int,
    ) -> BinaryInspection:
        if relative_path == "blocked.txt":
            return BinaryInspection(
                None,
                ContentStatus.UNREADABLE,
                InventoryWarning(
                    code=InventoryWarningCode.FILE_UNREADABLE,
                    relative_path=relative_path,
                    message="The file content could not be read safely.",
                ),
            )
        return super().inspect_binary(
            repository_root,
            relative_path,
            expected_size=expected_size,
        )


class FailOnSensitiveTextReader(SafeContentReader):
    """Prove that sensitive inventory entries are never opened as text."""

    def read_text(
        self,
        repository_root: Path,
        relative_path: str,
        *,
        expected_size: int,
        max_bytes: int | None = None,
    ) -> TextReadResult:
        if relative_path == ".env":
            raise AssertionError("sensitive content must not be opened")
        return super().read_text(
            repository_root,
            relative_path,
            expected_size=expected_size,
            max_bytes=max_bytes,
        )


def test_same_fixture_produces_equal_logical_result(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('data only')", encoding="utf-8")
    (tmp_path / "README.md").write_text("documentation", encoding="utf-8")

    service = InventoryService(inventory_limits)

    assert service.analyze(tmp_path) == service.analyze(tmp_path)


def test_warning_pairs_are_deduplicated_and_sorted(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "script").write_text("not a shebang", encoding="utf-8")
    reader = DuplicateWarningReader(inventory_limits)

    result = InventoryService(inventory_limits, content_reader=reader).analyze(tmp_path)

    assert len(result.warnings) == 1
    assert result.warnings[0].code is InventoryWarningCode.FILE_UNREADABLE
    assert result.warnings[0].relative_path == "script"


def test_warning_limit_retains_one_truncation_warning(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    for name in ("c", "a", "b"):
        (tmp_path / name).write_text("text", encoding="utf-8")
    reader = DuplicateWarningReader(inventory_limits)

    result = InventoryService(
        replace(inventory_limits, max_warnings=2),
        content_reader=reader,
    ).analyze(tmp_path)

    assert tuple(warning.code for warning in result.warnings) == (
        InventoryWarningCode.FILE_UNREADABLE,
        InventoryWarningCode.WARNING_LIMIT_REACHED,
    )
    assert result.warnings[0].relative_path == "a"
    assert result.warnings[1].relative_path is None


def test_result_contains_no_absolute_path_content_or_future_stage_fields(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    secret_value = "not-for-results"
    (tmp_path / ".env.example").write_text(secret_value, encoding="utf-8")
    (tmp_path / "README.md").write_text("private source body", encoding="utf-8")

    result = InventoryService(inventory_limits).analyze(tmp_path)
    serialized = repr(result)

    assert str(tmp_path) not in serialized
    assert secret_value not in serialized
    assert "private source body" not in serialized
    assert {field.name for field in fields(InventoryResult)} == {
        "schema_version",
        "repository_summary",
        "languages",
        "important_files",
        "technologies",
        "entry_points",
        "warnings",
    }


def test_broken_manifest_does_not_stop_other_technology_findings(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "package.json").write_text("{", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("private source", encoding="utf-8")

    result = InventoryService(inventory_limits).analyze(tmp_path)

    assert tuple(finding.name for finding in result.technologies) == ("Docker",)
    assert any(
        warning.code is InventoryWarningCode.MANIFEST_PARSE_FAILED for warning in result.warnings
    )


def test_manifest_warnings_are_deduplicated_and_sorted(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "requirements.txt").write_text(
        "-r one.txt\n-r two.txt\n",
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        json.dumps({"main": "../outside.js"}),
        encoding="utf-8",
    )

    result = InventoryService(inventory_limits).analyze(tmp_path)

    assert tuple((warning.code, warning.relative_path) for warning in result.warnings) == (
        (InventoryWarningCode.MANIFEST_ENTRY_SKIPPED, "requirements.txt"),
        (InventoryWarningCode.UNSAFE_MANIFEST_VALUE, "package.json"),
    )


def test_sensitive_file_is_never_opened_during_detection(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / ".env").write_text("PRIVATE_TOKEN=secret", encoding="utf-8")
    reader = FailOnSensitiveTextReader(inventory_limits)

    result = InventoryService(inventory_limits, content_reader=reader).analyze(tmp_path)

    assert result.repository_summary.sensitive_file_count == 1
    assert "PRIVATE_TOKEN" not in repr(result)


def test_summary_counts_ignored_binary_sensitive_unreadable_and_skipped_files(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "ignored" / "child").mkdir(parents=True)
    (tmp_path / "ignored" / "child" / "visible.txt").write_text("kept", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "hidden.js").write_text("hidden", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=value", encoding="utf-8")
    (tmp_path / "binary.dat").write_bytes(b"abc\x00def")
    (tmp_path / "large.txt").write_text("large text", encoding="utf-8")
    (tmp_path / "blocked.txt").write_text("blocked", encoding="utf-8")
    limits = replace(inventory_limits, max_text_read_bytes=4, binary_sample_bytes=4)
    reader = UnreadableContentReader(limits)

    summary = InventoryService(limits, content_reader=reader).analyze(tmp_path).repository_summary

    assert summary.regular_file_count == 5
    assert summary.ignored_directory_count == 1
    assert summary.binary_file_count == 1
    assert summary.sensitive_file_count == 1
    assert summary.unreadable_file_count == 1
    assert summary.skipped_content_file_count == 4


def test_fatal_scanner_error_returns_no_partial_result(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "one.txt").touch()
    (tmp_path / "two.txt").touch()
    service = InventoryService(replace(inventory_limits, max_entries=1))

    with pytest.raises(InventoryLimitExceeded):
        service.analyze(tmp_path)


def test_unexpected_failure_is_sanitized(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = InventoryService(inventory_limits)

    def fail_scan(_root: Path) -> None:
        raise RuntimeError(f"private content at {tmp_path}")

    monkeypatch.setattr(service._scanner, "scan", fail_scan)
    with pytest.raises(RepositoryAnalysisFailed) as raised:
        service.analyze(tmp_path)

    assert str(tmp_path) not in str(raised.value)
    assert "private content" not in str(raised.value)
    assert raised.value.__cause__ is None
