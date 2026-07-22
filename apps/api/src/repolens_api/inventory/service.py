"""Orchestration for one deterministic Stage 3A-1 inventory."""

import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from repolens_api.inventory.content import SafeContentReader
from repolens_api.inventory.contracts import (
    ContentStatus,
    FileInventoryEntry,
    InventoryLimits,
    InventoryResult,
    InventoryWarning,
    InventoryWarningCode,
    RepositorySummary,
)
from repolens_api.inventory.errors import InventoryError, RepositoryAnalysisFailed
from repolens_api.inventory.important_files import detect_important_files
from repolens_api.inventory.languages import detect_languages
from repolens_api.inventory.policy import categorize_file, path_sort_key
from repolens_api.inventory.scanner import RepositoryScan, RepositoryScanner

INVENTORY_SCHEMA_VERSION = 1


class InventoryService:
    """Build a bounded result without persisting or executing repository content."""

    def __init__(
        self,
        limits: InventoryLimits,
        *,
        content_reader: SafeContentReader | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits = limits
        self._content_reader = content_reader or SafeContentReader(limits)
        self._scanner = RepositoryScanner(
            limits,
            content_reader=self._content_reader,
            clock=clock,
        )

    def analyze(self, repository_root: Path) -> InventoryResult:
        """Return one logical inventory result or a safe fatal error."""
        try:
            scan = self._scanner.scan(repository_root)
            languages = detect_languages(repository_root, scan.files, self._content_reader)
            categorized_files = tuple(
                replace(
                    entry,
                    category=categorize_file(
                        entry.relative_path,
                        language=entry.language,
                        is_binary=entry.is_binary,
                    ),
                )
                for entry in languages.files
            )
            warnings = self._bounded_warnings((*scan.warnings, *languages.warnings))
            return InventoryResult(
                schema_version=INVENTORY_SCHEMA_VERSION,
                repository_summary=self._summary(scan, categorized_files),
                languages=languages.statistics,
                important_files=detect_important_files(categorized_files, scan.directories),
                warnings=warnings,
            )
        except InventoryError:
            raise
        except Exception:
            raise RepositoryAnalysisFailed from None

    def _bounded_warnings(
        self,
        warnings: tuple[InventoryWarning, ...],
    ) -> tuple[InventoryWarning, ...]:
        unique: dict[tuple[str, str], InventoryWarning] = {}
        for warning in warnings:
            key = (warning.code.value, warning.relative_path or "")
            unique.setdefault(key, warning)
        ordered = sorted(
            unique.values(),
            key=lambda warning: (
                warning.code.value,
                *path_sort_key(warning.relative_path or ""),
            ),
        )
        if len(ordered) <= self._limits.max_warnings:
            return tuple(ordered)

        limit_warning = InventoryWarning(
            code=InventoryWarningCode.WARNING_LIMIT_REACHED,
            relative_path=None,
            message="Additional inventory warnings were omitted.",
        )
        retained = ordered[: max(0, self._limits.max_warnings - 1)]
        retained.append(limit_warning)
        return tuple(
            sorted(
                retained,
                key=lambda warning: (
                    warning.code.value,
                    *path_sort_key(warning.relative_path or ""),
                ),
            )
        )

    @staticmethod
    def _summary(
        scan: RepositoryScan,
        files: tuple[FileInventoryEntry, ...],
    ) -> RepositorySummary:
        return RepositorySummary(
            regular_file_count=len(files),
            analyzed_directory_count=len(scan.directories),
            total_file_bytes=sum(entry.size_bytes for entry in files),
            max_directory_depth=scan.max_directory_depth,
            top_level_directories=scan.top_level_directories,
            directories_by_file_count=scan.directories_by_file_count,
            ignored_directory_count=scan.ignored_directory_count,
            binary_file_count=sum(entry.is_binary is True for entry in files),
            unreadable_file_count=sum(
                entry.content_status is ContentStatus.UNREADABLE for entry in files
            ),
            skipped_content_file_count=sum(
                entry.content_status is not ContentStatus.AVAILABLE for entry in files
            ),
            sensitive_file_count=sum(
                entry.content_status is ContentStatus.SENSITIVE for entry in files
            ),
        )
