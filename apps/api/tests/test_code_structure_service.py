"""Tests for bounded source-structure orchestration and safety policies."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import NoReturn, cast

import pytest

from repolens_api.code_structure.contracts import (
    SourceParseStatus,
    SourceStructureLimits,
    SourceStructureWarningCode,
)
from repolens_api.code_structure.errors import (
    SourceStructureLimitExceeded,
    SourceStructureTimeout,
    UnsafeSourcePath,
)
from repolens_api.code_structure.parsers import SourceParserRegistry
from repolens_api.code_structure.service import CodeStructureService
from repolens_api.inventory.content import SafeContentReader, TextReadResult
from repolens_api.inventory.contracts import (
    ContentStatus,
    FileCategory,
    FileInventoryEntry,
    InventoryLimits,
)


def _limits(**overrides: int) -> SourceStructureLimits:
    values = {
        "timeout_seconds": 5,
        "max_source_file_bytes": 512,
        "max_structure_files": 20,
        "max_source_symbols": 100,
        "max_source_imports": 100,
        "max_symbols_per_file": 20,
        "max_imports_per_file": 20,
        "max_imported_names_per_import": 10,
        "max_warnings": 20,
    }
    values.update(overrides)
    return SourceStructureLimits(**values)


def _inventory_limits() -> InventoryLimits:
    return InventoryLimits(
        timeout_seconds=5,
        max_entries=100,
        max_directories=50,
        max_path_length=200,
        max_manifest_bytes=512,
        max_text_read_bytes=512,
        binary_sample_bytes=64,
        max_warnings=20,
        max_json_nesting_depth=8,
        max_manifest_nodes=100,
        max_technology_findings=20,
        max_technology_evidence_per_finding=5,
        max_entry_points=20,
    )


def _entry(
    relative_path: str,
    content: bytes,
    *,
    category: FileCategory = FileCategory.SOURCE,
    status: ContentStatus = ContentStatus.AVAILABLE,
    is_binary: bool | None = False,
) -> FileInventoryEntry:
    path = Path(relative_path)
    return FileInventoryEntry(
        relative_path=relative_path,
        name=path.name,
        extension=path.suffix.casefold(),
        size_bytes=len(content),
        language=None,
        category=category,
        is_binary=is_binary,
        content_status=status,
    )


def _service(
    limits: SourceStructureLimits | None = None,
    *,
    reader: SafeContentReader | None = None,
    clock: Callable[[], float] | None = None,
) -> CodeStructureService:
    content_reader = reader or SafeContentReader(_inventory_limits())
    if clock is None:
        return CodeStructureService(limits or _limits(), content_reader=content_reader)
    return CodeStructureService(
        limits or _limits(),
        content_reader=content_reader,
        clock=clock,
    )


def test_service_analyzes_supported_files_and_preserves_category(tmp_path: Path) -> None:
    python = b"import os\nclass Demo:\n    def method(self):\n        pass\n"
    typescript = b'export const start = async () => 1;\nimport {x} from "pkg";\n'
    ignored = b"package main"
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_bytes(python)
    (tmp_path / "src" / "main.ts").write_bytes(typescript)
    (tmp_path / "src" / "main.go").write_bytes(ignored)
    files = (
        _entry("src/main.py", python, category=FileCategory.TEST),
        _entry("src/main.ts", typescript),
        _entry("src/main.go", ignored),
    )

    result = _service().analyze(tmp_path.resolve(), files)

    assert result.summary.supported_source_file_count == 2
    assert result.summary.parsed_file_count == 2
    assert result.summary.skipped_file_count == 0
    assert result.summary.total_symbol_count == 3
    assert result.summary.total_class_count == 1
    assert result.summary.total_method_count == 1
    assert result.summary.total_function_count == 1
    assert result.summary.total_import_count == 2
    assert tuple(item.language for item in result.summary.language_file_counts) == (
        "Python",
        "TypeScript",
    )
    assert result.files[0].category is FileCategory.TEST
    assert all(item.parse_status is SourceParseStatus.PARSED for item in result.files)


@pytest.mark.parametrize(
    ("content", "status", "is_binary", "expected_warning"),
    [
        (
            b"x" * 20,
            ContentStatus.AVAILABLE,
            False,
            SourceStructureWarningCode.SOURCE_FILE_TOO_LARGE,
        ),
        (
            b"\x00binary",
            ContentStatus.BINARY,
            True,
            SourceStructureWarningCode.UNSUPPORTED_SOURCE_ENCODING,
        ),
        (
            b"\xff\xfe",
            ContentStatus.AVAILABLE,
            False,
            SourceStructureWarningCode.UNSUPPORTED_SOURCE_ENCODING,
        ),
    ],
)
def test_unsafe_or_unsupported_content_is_skipped_with_safe_warning(
    tmp_path: Path,
    content: bytes,
    status: ContentStatus,
    is_binary: bool,
    expected_warning: SourceStructureWarningCode,
) -> None:
    path = tmp_path / "source.py"
    path.write_bytes(content)
    limit = 10 if expected_warning is SourceStructureWarningCode.SOURCE_FILE_TOO_LARGE else 512

    result = _service(_limits(max_source_file_bytes=limit)).analyze(
        tmp_path.resolve(),
        (_entry("source.py", content, status=status, is_binary=is_binary),),
    )

    assert result.files[0].parse_status is SourceParseStatus.SKIPPED
    assert result.symbols == ()
    assert result.warnings[0].code is expected_warning
    assert str(tmp_path) not in result.warnings[0].message
    assert "binary" not in result.warnings[0].message.casefold() or expected_warning is (
        SourceStructureWarningCode.UNSUPPORTED_SOURCE_ENCODING
    )


def test_sensitive_source_file_is_never_opened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"PRIVATE_SOURCE_BODY"
    (tmp_path / "credentials.py").write_bytes(content)
    reader = SafeContentReader(_inventory_limits())

    def fail_read(*_args: object, **_kwargs: object) -> TextReadResult:
        raise AssertionError("sensitive content must not be opened")

    monkeypatch.setattr(reader, "read_text", fail_read)
    result = _service(reader=reader).analyze(
        tmp_path.resolve(),
        (
            _entry(
                "credentials.py",
                content,
                status=ContentStatus.SENSITIVE,
                is_binary=None,
            ),
        ),
    )

    assert result.files[0].parse_status is SourceParseStatus.SKIPPED
    assert result.warnings == ()
    assert result.symbols == ()


def test_unreadable_source_file_uses_fixed_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"def private_source_body(): pass"
    (tmp_path / "module.py").write_bytes(content)
    reader = SafeContentReader(_inventory_limits())

    def unreadable(*_args: object, **_kwargs: object) -> TextReadResult:
        return TextReadResult(None, ContentStatus.UNREADABLE)

    monkeypatch.setattr(reader, "read_text", unreadable)
    result = _service(reader=reader).analyze(
        tmp_path.resolve(),
        (_entry("module.py", content),),
    )

    assert result.warnings[0].code is SourceStructureWarningCode.SOURCE_FILE_UNREADABLE
    assert "private_source_body" not in result.warnings[0].message


def test_parser_exception_is_isolated_without_detail_or_source_leak(tmp_path: Path) -> None:
    content = b"def private_source_body(): pass"
    (tmp_path / "module.py").write_bytes(content)

    class ExplodingParser:
        def parse(
            self,
            _relative_path: str,
            _language: str,
            _source: str,
        ) -> NoReturn:
            raise RuntimeError("PRIVATE_SOURCE_BODY C:\\private\\workspace")

    class ExplodingRegistry:
        def for_language(self, _language: str) -> ExplodingParser:
            return ExplodingParser()

    service = CodeStructureService(
        _limits(),
        content_reader=SafeContentReader(_inventory_limits()),
        parsers=cast(SourceParserRegistry, ExplodingRegistry()),
    )
    result = service.analyze(tmp_path.resolve(), (_entry("module.py", content),))

    assert result.files[0].parse_status is SourceParseStatus.FAILED
    assert result.warnings[0].code is SourceStructureWarningCode.SOURCE_PARSE_FAILED
    assert "PRIVATE_SOURCE_BODY" not in repr(result)
    assert str(tmp_path) not in repr(result)


@pytest.mark.parametrize(
    ("limit_name", "limit_value", "file_contents"),
    [
        ("max_structure_files", 1, (b"def one(): pass", b"def two(): pass")),
        (
            "max_source_symbols",
            1,
            (b"def one(): pass\ndef two(): pass",),
        ),
        (
            "max_source_imports",
            1,
            (b"import one\nimport two",),
        ),
    ],
)
def test_global_limits_are_fatal_without_partial_result(
    tmp_path: Path,
    limit_name: str,
    limit_value: int,
    file_contents: tuple[bytes, ...],
) -> None:
    entries: list[FileInventoryEntry] = []
    for index, content in enumerate(file_contents):
        name = f"module_{index}.py"
        (tmp_path / name).write_bytes(content)
        entries.append(_entry(name, content))

    with pytest.raises(SourceStructureLimitExceeded):
        _service(_limits(**{limit_name: limit_value})).analyze(
            tmp_path.resolve(),
            tuple(entries),
        )


def test_per_file_limits_truncate_deterministically_with_warnings(tmp_path: Path) -> None:
    content = b"import one\nimport two\ndef one(): pass\ndef two(): pass"
    (tmp_path / "module.py").write_bytes(content)

    result = _service(_limits(max_symbols_per_file=1, max_imports_per_file=1)).analyze(
        tmp_path.resolve(), (_entry("module.py", content),)
    )

    assert tuple(item.name for item in result.symbols) == ("one",)
    assert tuple(item.module for item in result.imports) == ("one",)
    assert {warning.code for warning in result.warnings} == {
        SourceStructureWarningCode.SOURCE_IMPORTS_TRUNCATED,
        SourceStructureWarningCode.SOURCE_SYMBOLS_TRUNCATED,
    }


def test_timeout_uses_one_monotonic_repository_deadline(tmp_path: Path) -> None:
    content = b"def function(): pass"
    (tmp_path / "module.py").write_bytes(content)
    moments = iter((0.0, 2.0))

    with pytest.raises(SourceStructureTimeout):
        _service(_limits(timeout_seconds=1), clock=lambda: next(moments)).analyze(
            tmp_path.resolve(),
            (_entry("module.py", content),),
        )


def test_warning_limit_replaces_excess_with_fixed_marker(tmp_path: Path) -> None:
    entries: list[FileInventoryEntry] = []
    for name in ("one.py", "two.py"):
        content = b"\xff"
        (tmp_path / name).write_bytes(content)
        entries.append(_entry(name, content))

    result = _service(_limits(max_warnings=1)).analyze(
        tmp_path.resolve(),
        tuple(entries),
    )

    assert len(result.warnings) == 1
    assert result.warnings[0].code is (SourceStructureWarningCode.STRUCTURE_WARNING_LIMIT_REACHED)


def test_absolute_inventory_path_is_rejected_without_path_leak(tmp_path: Path) -> None:
    absolute = (tmp_path / "private.py").resolve()
    content = b"def secret(): pass"
    absolute.write_bytes(content)
    entry = replace(_entry("private.py", content), relative_path=str(absolute))

    with pytest.raises(UnsafeSourcePath) as raised:
        _service().analyze(tmp_path.resolve(), (entry,))

    assert str(tmp_path) not in str(raised.value)
