"""Tests for deterministic language assignment and statistics."""

from pathlib import Path, PurePosixPath

import pytest

from repolens_api.inventory.content import SafeContentReader
from repolens_api.inventory.contracts import (
    ContentStatus,
    FileCategory,
    FileInventoryEntry,
    InventoryLimits,
)
from repolens_api.inventory.languages import detect_languages


def _entry(
    name: str,
    *,
    size: int = 1,
    is_binary: bool | None = False,
    content_status: ContentStatus = ContentStatus.AVAILABLE,
) -> FileInventoryEntry:
    return FileInventoryEntry(
        relative_path=name,
        name=PurePosixPath(name).name,
        extension=PurePosixPath(name).suffix,
        size_bytes=size,
        language=None,
        category=FileCategory.OTHER,
        is_binary=is_binary,
        content_status=content_status,
    )


@pytest.mark.parametrize(
    ("extension", "language"),
    [
        (".py", "Python"),
        (".pyi", "Python"),
        (".ts", "TypeScript"),
        (".tsx", "TypeScript"),
        (".mts", "TypeScript"),
        (".cts", "TypeScript"),
        (".js", "JavaScript"),
        (".jsx", "JavaScript"),
        (".mjs", "JavaScript"),
        (".cjs", "JavaScript"),
        (".cs", "C#"),
        (".c", "C"),
        (".cc", "C++"),
        (".cpp", "C++"),
        (".cxx", "C++"),
        (".c++", "C++"),
        (".hpp", "C++"),
        (".hh", "C++"),
        (".hxx", "C++"),
        (".java", "Java"),
        (".kt", "Kotlin"),
        (".kts", "Kotlin"),
        (".go", "Go"),
        (".rs", "Rust"),
        (".php", "PHP"),
        (".rb", "Ruby"),
        (".html", "HTML"),
        (".htm", "HTML"),
        (".css", "CSS"),
        (".sh", "Shell"),
        (".bash", "Shell"),
        (".zsh", "Shell"),
        (".ps1", "PowerShell"),
        (".psm1", "PowerShell"),
        (".psd1", "PowerShell"),
        (".sql", "SQL"),
        (".yaml", "YAML"),
        (".yml", "YAML"),
        (".json", "JSON"),
        (".toml", "TOML"),
        (".xml", "XML"),
        (".md", "Markdown"),
        (".markdown", "Markdown"),
        (".mdown", "Markdown"),
    ],
)
def test_supported_extension_mapping(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
    extension: str,
    language: str,
) -> None:
    detection = detect_languages(
        tmp_path,
        (_entry(f"file{extension}"),),
        SafeContentReader(inventory_limits),
    )

    assert detection.files[0].language == language


def test_extension_mapping_is_case_insensitive(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    detection = detect_languages(
        tmp_path,
        (_entry("MAIN.PY"), _entry("WEB.TSX")),
        SafeContentReader(inventory_limits),
    )

    assert tuple(entry.language for entry in detection.files) == ("Python", "TypeScript")


@pytest.mark.parametrize("name", ["Gemfile", "RAKEFILE"])
def test_ruby_special_filenames(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
    name: str,
) -> None:
    detection = detect_languages(
        tmp_path,
        (_entry(name),),
        SafeContentReader(inventory_limits),
    )

    assert detection.files[0].language == "Ruby"


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        (("main.c",), "C"),
        (("main.cpp",), "C++"),
        (("main.c", "main.cpp"), None),
        ((), None),
    ],
)
def test_header_ambiguity_uses_repository_evidence(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
    evidence: tuple[str, ...],
    expected: str | None,
) -> None:
    files = tuple(_entry(name) for name in (*evidence, "shared.h"))

    detection = detect_languages(tmp_path, files, SafeContentReader(inventory_limits))

    assert detection.files[-1].language == expected


@pytest.mark.parametrize(
    ("first_line", "expected"),
    [
        ("#!/usr/bin/env python3", "Python"),
        ("#!/bin/bash -eu", "Shell"),
        ("#!/usr/bin/env -S ruby -w", "Ruby"),
    ],
)
def test_allowlisted_shebang_detection(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
    first_line: str,
    expected: str,
) -> None:
    content = f"{first_line}\nignored body"
    path = tmp_path / "script"
    path.write_text(content, encoding="utf-8")

    detection = detect_languages(
        tmp_path,
        (_entry("script", size=path.stat().st_size),),
        SafeContentReader(inventory_limits),
    )

    assert detection.files[0].language == expected


def test_unknown_extension_remains_unknown(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    detection = detect_languages(
        tmp_path,
        (_entry("unknown.xyz"),),
        SafeContentReader(inventory_limits),
    )

    assert detection.files[0].language is None
    assert detection.statistics == ()


def test_binary_and_sensitive_files_are_excluded_from_statistics(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    files = (
        _entry("binary.py", size=10, is_binary=True, content_status=ContentStatus.BINARY),
        _entry(
            ".env.py",
            size=20,
            is_binary=None,
            content_status=ContentStatus.SENSITIVE,
        ),
        _entry("source.py", size=5),
    )

    detection = detect_languages(tmp_path, files, SafeContentReader(inventory_limits))

    assert len(detection.statistics) == 1
    assert detection.statistics[0].file_count == 1
    assert detection.statistics[0].total_bytes == 5
    assert detection.statistics[0].percentage == 100.0


def test_language_percentages_use_supported_non_binary_bytes(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    files = (_entry("main.py", size=3), _entry("index.js", size=1), _entry("data.xyz", size=8))

    statistics = detect_languages(
        tmp_path,
        files,
        SafeContentReader(inventory_limits),
    ).statistics

    assert [(item.name, item.percentage) for item in statistics] == [
        ("Python", 75.0),
        ("JavaScript", 25.0),
    ]


def test_zero_byte_denominator_produces_zero_percentage(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    statistics = detect_languages(
        tmp_path,
        (_entry("empty.py", size=0),),
        SafeContentReader(inventory_limits),
    ).statistics

    assert statistics[0].percentage == 0.0


def test_language_order_uses_bytes_then_name(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    files = (_entry("main.py", size=2), _entry("index.js", size=2), _entry("types.ts", size=3))

    statistics = detect_languages(
        tmp_path,
        files,
        SafeContentReader(inventory_limits),
    ).statistics

    assert tuple(item.name for item in statistics) == ("TypeScript", "JavaScript", "Python")
