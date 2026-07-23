"""Bounded orchestration for deterministic source-structure analysis."""

import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from repolens_api.code_structure.contracts import (
    SOURCE_STRUCTURE_WARNING_MESSAGES,
    CodeStructureResult,
    CodeStructureSummary,
    ImportFinding,
    LanguageFileCount,
    ParsedSourceStructure,
    SourceFileStructure,
    SourceParseStatus,
    SourceStructureLimits,
    SourceStructureWarning,
    SourceStructureWarningCode,
    SourceSymbol,
    SourceSymbolKind,
)
from repolens_api.code_structure.errors import (
    SourceStructureError,
    SourceStructureFailed,
    SourceStructureLimitExceeded,
    SourceStructureTimeout,
    UnsafeSourcePath,
)
from repolens_api.code_structure.parsers import SourceParserRegistry
from repolens_api.code_structure.policy import (
    source_import_sort_key,
    source_symbol_sort_key,
    supported_language,
)
from repolens_api.inventory.content import SafeContentReader
from repolens_api.inventory.contracts import (
    ContentStatus,
    FileInventoryEntry,
)
from repolens_api.inventory.errors import UnsafeRepositoryPath
from repolens_api.inventory.policy import path_sort_key


class CodeStructureService:
    """Analyze only supported safe inventory files under explicit limits."""

    def __init__(
        self,
        limits: SourceStructureLimits,
        *,
        content_reader: SafeContentReader,
        parsers: SourceParserRegistry | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits = limits
        self._content_reader = content_reader
        self._parsers = parsers or SourceParserRegistry(
            max_imported_names_per_import=limits.max_imported_names_per_import
        )
        self._clock = clock

    def analyze(
        self,
        repository_root: Path,
        inventory_files: tuple[FileInventoryEntry, ...],
    ) -> CodeStructureResult:
        """Return bounded structure for supported source inventory entries."""
        try:
            candidates = tuple(
                sorted(
                    (
                        (entry, language)
                        for entry in inventory_files
                        if (language := supported_language(entry.relative_path)) is not None
                    ),
                    key=lambda item: path_sort_key(item[0].relative_path),
                )
            )
            if len(candidates) > self._limits.max_structure_files:
                raise SourceStructureLimitExceeded

            deadline = self._clock() + self._limits.timeout_seconds
            files: list[SourceFileStructure] = []
            symbols: list[SourceSymbol] = []
            imports: list[ImportFinding] = []
            warnings: list[SourceStructureWarning] = []

            for entry, language in candidates:
                self._check_deadline(deadline)
                parsed, file_warnings, line_count = self._parse_file(
                    repository_root,
                    entry,
                    language,
                )
                retained_symbols, retained_imports, truncation_warnings = self._apply_file_limits(
                    entry.relative_path,
                    parsed,
                )
                if len(symbols) + len(retained_symbols) > self._limits.max_source_symbols:
                    raise SourceStructureLimitExceeded
                if len(imports) + len(retained_imports) > self._limits.max_source_imports:
                    raise SourceStructureLimitExceeded
                symbols.extend(retained_symbols)
                imports.extend(retained_imports)
                warnings.extend((*file_warnings, *truncation_warnings))
                files.append(
                    self._file_structure(
                        entry,
                        language,
                        line_count,
                        retained_symbols,
                        retained_imports,
                        parsed,
                    )
                )
                self._check_deadline(deadline)

            ordered_files = tuple(sorted(files, key=lambda item: path_sort_key(item.relative_path)))
            ordered_symbols = tuple(
                sorted(
                    symbols,
                    key=lambda item: source_symbol_sort_key(
                        item.relative_path,
                        item.start_line,
                        item.qualified_name,
                        item.kind.value,
                    ),
                )
            )
            ordered_imports = tuple(
                sorted(
                    imports,
                    key=lambda item: source_import_sort_key(
                        item.relative_path,
                        item.start_line,
                        item.module,
                        item.import_kind.value,
                    ),
                )
            )
            return CodeStructureResult(
                summary=self._summary(ordered_files, ordered_symbols, ordered_imports),
                files=ordered_files,
                symbols=ordered_symbols,
                imports=ordered_imports,
                warnings=self._bounded_warnings(warnings),
            )
        except SourceStructureError:
            raise
        except UnsafeRepositoryPath:
            raise UnsafeSourcePath from None
        except Exception:
            raise SourceStructureFailed from None

    def _parse_file(
        self,
        repository_root: Path,
        entry: FileInventoryEntry,
        language: str,
    ) -> tuple[
        ParsedSourceStructure,
        tuple[SourceStructureWarning, ...],
        int,
    ]:
        skipped_code = self._skip_code(entry)
        if skipped_code is not None:
            warnings = (
                ()
                if entry.content_status is ContentStatus.SENSITIVE
                else (self._warning(skipped_code, entry.relative_path),)
            )
            return ParsedSourceStructure((), (), False, skipped=True), warnings, 0

        read = self._content_reader.read_text(
            repository_root,
            entry.relative_path,
            expected_size=entry.size_bytes,
            max_bytes=self._limits.max_source_file_bytes,
        )
        if read.text is None:
            warning_code = {
                ContentStatus.TOO_LARGE: SourceStructureWarningCode.SOURCE_FILE_TOO_LARGE,
                ContentStatus.UNREADABLE: SourceStructureWarningCode.SOURCE_FILE_UNREADABLE,
            }.get(read.content_status, SourceStructureWarningCode.UNSUPPORTED_SOURCE_ENCODING)
            return (
                ParsedSourceStructure((), (), False, skipped=True),
                (self._warning(warning_code, entry.relative_path),),
                0,
            )

        line_count = 0 if not read.text else read.text.count("\n") + 1
        try:
            parsed = self._parsers.for_language(language).parse(
                entry.relative_path,
                language,
                read.text,
            )
        except Exception:
            return (
                ParsedSourceStructure((), (), False, parse_failed=True),
                (
                    self._warning(
                        SourceStructureWarningCode.SOURCE_PARSE_FAILED,
                        entry.relative_path,
                    ),
                ),
                line_count,
            )

        warnings = (
            (
                self._warning(
                    SourceStructureWarningCode.SOURCE_SYNTAX_ERROR,
                    entry.relative_path,
                ),
            )
            if parsed.has_syntax_errors
            else ()
        )
        return parsed, warnings, line_count

    def _apply_file_limits(
        self,
        relative_path: str,
        parsed: ParsedSourceStructure,
    ) -> tuple[
        tuple[SourceSymbol, ...],
        tuple[ImportFinding, ...],
        tuple[SourceStructureWarning, ...],
    ]:
        symbols = parsed.symbols[: self._limits.max_symbols_per_file]
        imports = parsed.imports[: self._limits.max_imports_per_file]
        warnings: list[SourceStructureWarning] = []
        if parsed.symbols_truncated or len(parsed.symbols) > len(symbols):
            warnings.append(
                self._warning(
                    SourceStructureWarningCode.SOURCE_SYMBOLS_TRUNCATED,
                    relative_path,
                )
            )
        if parsed.imports_truncated or len(parsed.imports) > len(imports):
            warnings.append(
                self._warning(
                    SourceStructureWarningCode.SOURCE_IMPORTS_TRUNCATED,
                    relative_path,
                )
            )
        return symbols, imports, tuple(warnings)

    @staticmethod
    def _file_structure(
        entry: FileInventoryEntry,
        language: str,
        line_count: int,
        symbols: tuple[SourceSymbol, ...],
        imports: tuple[ImportFinding, ...],
        parsed: ParsedSourceStructure,
    ) -> SourceFileStructure:
        status = SourceParseStatus.PARSED
        if parsed.skipped:
            status = SourceParseStatus.SKIPPED
        elif parsed.parse_failed:
            status = SourceParseStatus.FAILED
        elif parsed.has_syntax_errors:
            status = SourceParseStatus.PARTIAL
        return SourceFileStructure(
            relative_path=entry.relative_path,
            language=language,
            category=entry.category,
            line_count=line_count,
            symbol_count=len(symbols),
            import_count=len(imports),
            class_count=sum(item.kind is SourceSymbolKind.CLASS for item in symbols),
            function_count=sum(
                item.kind in {SourceSymbolKind.FUNCTION, SourceSymbolKind.ASYNC_FUNCTION}
                for item in symbols
            ),
            method_count=sum(
                item.kind in {SourceSymbolKind.METHOD, SourceSymbolKind.ASYNC_METHOD}
                for item in symbols
            ),
            parse_status=status,
            has_syntax_errors=parsed.has_syntax_errors,
        )

    @staticmethod
    def _summary(
        files: tuple[SourceFileStructure, ...],
        symbols: tuple[SourceSymbol, ...],
        imports: tuple[ImportFinding, ...],
    ) -> CodeStructureSummary:
        language_counts = Counter(item.language for item in files)
        return CodeStructureSummary(
            supported_source_file_count=len(files),
            parsed_file_count=sum(
                item.parse_status in {SourceParseStatus.PARSED, SourceParseStatus.PARTIAL}
                for item in files
            ),
            skipped_file_count=sum(
                item.parse_status is SourceParseStatus.SKIPPED for item in files
            ),
            parse_error_file_count=sum(
                item.parse_status is SourceParseStatus.FAILED or item.has_syntax_errors
                for item in files
            ),
            total_symbol_count=len(symbols),
            total_function_count=sum(
                item.kind in {SourceSymbolKind.FUNCTION, SourceSymbolKind.ASYNC_FUNCTION}
                for item in symbols
            ),
            total_class_count=sum(item.kind is SourceSymbolKind.CLASS for item in symbols),
            total_method_count=sum(
                item.kind in {SourceSymbolKind.METHOD, SourceSymbolKind.ASYNC_METHOD}
                for item in symbols
            ),
            total_import_count=len(imports),
            language_file_counts=tuple(
                LanguageFileCount(language=language, file_count=count)
                for language, count in sorted(
                    language_counts.items(),
                    key=lambda item: (item[0].casefold(), item[0]),
                )
            ),
        )

    def _bounded_warnings(
        self,
        warnings: list[SourceStructureWarning],
    ) -> tuple[SourceStructureWarning, ...]:
        unique = {
            (warning.code.value, warning.relative_path or ""): warning for warning in warnings
        }
        ordered = sorted(
            unique.values(),
            key=lambda warning: (
                warning.code.value,
                *path_sort_key(warning.relative_path or ""),
            ),
        )
        if len(ordered) <= self._limits.max_warnings:
            return tuple(ordered)
        limit_warning = self._warning(
            SourceStructureWarningCode.STRUCTURE_WARNING_LIMIT_REACHED,
            None,
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

    def _skip_code(
        self,
        entry: FileInventoryEntry,
    ) -> SourceStructureWarningCode | None:
        if entry.size_bytes > self._limits.max_source_file_bytes:
            return SourceStructureWarningCode.SOURCE_FILE_TOO_LARGE
        if entry.content_status is ContentStatus.SENSITIVE:
            return SourceStructureWarningCode.SOURCE_FILE_UNREADABLE
        if entry.content_status is ContentStatus.UNREADABLE:
            return SourceStructureWarningCode.SOURCE_FILE_UNREADABLE
        if (
            entry.content_status
            in {
                ContentStatus.BINARY,
                ContentStatus.UNSUPPORTED_ENCODING,
            }
            or entry.is_binary is not False
        ):
            return SourceStructureWarningCode.UNSUPPORTED_SOURCE_ENCODING
        return None

    def _check_deadline(self, deadline: float) -> None:
        if self._clock() >= deadline:
            raise SourceStructureTimeout

    @staticmethod
    def _warning(
        code: SourceStructureWarningCode,
        relative_path: str | None,
    ) -> SourceStructureWarning:
        return SourceStructureWarning(
            code=code,
            relative_path=relative_path,
            message=SOURCE_STRUCTURE_WARNING_MESSAGES[code],
        )
