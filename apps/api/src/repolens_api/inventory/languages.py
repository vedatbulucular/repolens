"""Deterministic language detection from safe repository metadata."""

import re
from dataclasses import dataclass, replace
from pathlib import Path

from repolens_api.inventory.content import SafeContentReader
from repolens_api.inventory.contracts import (
    ContentStatus,
    FileInventoryEntry,
    InventoryWarning,
    LanguageStatistic,
)

EXTENSION_LANGUAGES: dict[str, str] = {
    ".py": "Python",
    ".pyi": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".mts": "TypeScript",
    ".cts": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".cs": "C#",
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cxx": "C++",
    ".c++": "C++",
    ".hpp": "C++",
    ".hh": "C++",
    ".hxx": "C++",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".go": "Go",
    ".rs": "Rust",
    ".php": "PHP",
    ".rb": "Ruby",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".ps1": "PowerShell",
    ".psm1": "PowerShell",
    ".psd1": "PowerShell",
    ".sql": "SQL",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".xml": "XML",
    ".md": "Markdown",
    ".markdown": "Markdown",
    ".mdown": "Markdown",
}

RUBY_SPECIAL_FILENAMES = frozenset({"gemfile", "rakefile"})
C_EXTENSIONS = frozenset({".c"})
CPP_EVIDENCE_EXTENSIONS = frozenset({".c++", ".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx"})
SHEBANG_PATTERN = re.compile(
    r"^#!\s*(?:(?:/usr/bin/env)(?:\s+-S)?\s+)?(?:\S*/)?"
    r"(?P<interpreter>python(?:\d+(?:\.\d+)*)?|bash|dash|ksh|sh|zsh|ruby)(?:\s|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class LanguageDetection:
    """Updated file metadata, statistics, and safe read warnings."""

    files: tuple[FileInventoryEntry, ...]
    statistics: tuple[LanguageStatistic, ...]
    warnings: tuple[InventoryWarning, ...]


def detect_languages(
    repository_root: Path,
    files: tuple[FileInventoryEntry, ...],
    content_reader: SafeContentReader,
) -> LanguageDetection:
    """Assign supported languages using two-pass metadata and bounded shebang reads."""
    c_evidence = any(
        entry.extension.casefold() in C_EXTENSIONS and entry.is_binary is False for entry in files
    )
    cpp_evidence = any(
        entry.extension.casefold() in CPP_EVIDENCE_EXTENSIONS and entry.is_binary is False
        for entry in files
    )
    header_language = _header_language(c_evidence=c_evidence, cpp_evidence=cpp_evidence)

    detected_files: list[FileInventoryEntry] = []
    warnings: list[InventoryWarning] = []
    for entry in files:
        language = _metadata_language(entry, header_language)
        updated = replace(entry, language=language)
        if language is None and entry.extension == "" and _can_read_shebang(entry):
            text_result = content_reader.read_text(
                repository_root,
                entry.relative_path,
                expected_size=entry.size_bytes,
            )
            if text_result.warning is not None:
                warnings.append(text_result.warning)
            if text_result.content_status is not ContentStatus.AVAILABLE:
                updated = replace(
                    updated,
                    content_status=text_result.content_status,
                    is_binary=(
                        True
                        if text_result.content_status is ContentStatus.BINARY
                        else updated.is_binary
                    ),
                )
            if text_result.text is not None:
                updated = replace(updated, language=_shebang_language(text_result.text))
        detected_files.append(updated)

    immutable_files = tuple(detected_files)
    return LanguageDetection(
        files=immutable_files,
        statistics=build_language_statistics(immutable_files),
        warnings=tuple(warnings),
    )


def build_language_statistics(
    files: tuple[FileInventoryEntry, ...],
) -> tuple[LanguageStatistic, ...]:
    """Aggregate supported, non-binary, non-sensitive file bytes."""
    grouped: dict[str, tuple[int, int]] = {}
    for entry in files:
        if (
            entry.language is None
            or entry.is_binary is not False
            or entry.content_status is ContentStatus.SENSITIVE
        ):
            continue
        count, total_bytes = grouped.get(entry.language, (0, 0))
        grouped[entry.language] = (count + 1, total_bytes + entry.size_bytes)

    denominator = sum(total_bytes for _, total_bytes in grouped.values())
    statistics = [
        LanguageStatistic(
            name=name,
            file_count=count,
            total_bytes=total_bytes,
            percentage=(round(total_bytes * 100 / denominator, 2) if denominator else 0.0),
        )
        for name, (count, total_bytes) in grouped.items()
    ]
    return tuple(sorted(statistics, key=lambda item: (-item.total_bytes, item.name)))


def _metadata_language(entry: FileInventoryEntry, header_language: str | None) -> str | None:
    if entry.name.casefold() in RUBY_SPECIAL_FILENAMES:
        return "Ruby"
    extension = entry.extension.casefold()
    if extension == ".h":
        return header_language
    return EXTENSION_LANGUAGES.get(extension)


def _header_language(*, c_evidence: bool, cpp_evidence: bool) -> str | None:
    if c_evidence == cpp_evidence:
        return None
    return "C" if c_evidence else "C++"


def _can_read_shebang(entry: FileInventoryEntry) -> bool:
    return entry.is_binary is False and entry.content_status is ContentStatus.AVAILABLE


def _shebang_language(text: str) -> str | None:
    first_line = text.splitlines()[0] if text else ""
    match = SHEBANG_PATTERN.match(first_line)
    if match is None:
        return None
    interpreter = match.group("interpreter").casefold()
    if interpreter.startswith("python"):
        return "Python"
    if interpreter == "ruby":
        return "Ruby"
    return "Shell"
