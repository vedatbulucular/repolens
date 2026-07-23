"""Immutable contracts for bounded source-structure analysis."""

from dataclasses import dataclass
from enum import StrEnum

from repolens_api.inventory.contracts import FileCategory


class SourceSymbolKind(StrEnum):
    """Supported structural symbol kinds."""

    FUNCTION = "function"
    ASYNC_FUNCTION = "async_function"
    CLASS = "class"
    METHOD = "method"
    ASYNC_METHOD = "async_method"


class SourceImportKind(StrEnum):
    """Supported import syntax families."""

    PYTHON_IMPORT = "python_import"
    PYTHON_FROM_IMPORT = "python_from_import"
    ECMASCRIPT_IMPORT = "ecmascript_import"
    COMMONJS_REQUIRE = "commonjs_require"


class SourceParseStatus(StrEnum):
    """Safe per-file parse outcome."""

    PARSED = "parsed"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class SourceStructureWarningCode(StrEnum):
    """Non-fatal source-analysis warning codes."""

    SOURCE_PARSE_FAILED = "source_parse_failed"
    SOURCE_SYNTAX_ERROR = "source_syntax_error"
    UNSUPPORTED_SOURCE_ENCODING = "unsupported_source_encoding"
    SOURCE_FILE_TOO_LARGE = "source_file_too_large"
    SOURCE_FILE_UNREADABLE = "source_file_unreadable"
    SOURCE_SYMBOLS_TRUNCATED = "source_symbols_truncated"
    SOURCE_IMPORTS_TRUNCATED = "source_imports_truncated"
    STRUCTURE_WARNING_LIMIT_REACHED = "structure_warning_limit_reached"


SOURCE_STRUCTURE_WARNING_MESSAGES: dict[SourceStructureWarningCode, str] = {
    SourceStructureWarningCode.SOURCE_PARSE_FAILED: ("The source file could not be parsed safely."),
    SourceStructureWarningCode.SOURCE_SYNTAX_ERROR: ("The source file contains syntax errors."),
    SourceStructureWarningCode.UNSUPPORTED_SOURCE_ENCODING: (
        "The source file uses an unsupported encoding or contains binary data."
    ),
    SourceStructureWarningCode.SOURCE_FILE_TOO_LARGE: (
        "The source file exceeds the allowed parse size."
    ),
    SourceStructureWarningCode.SOURCE_FILE_UNREADABLE: (
        "The source file could not be read safely."
    ),
    SourceStructureWarningCode.SOURCE_SYMBOLS_TRUNCATED: (
        "Additional source symbols were omitted."
    ),
    SourceStructureWarningCode.SOURCE_IMPORTS_TRUNCATED: (
        "Additional source imports were omitted."
    ),
    SourceStructureWarningCode.STRUCTURE_WARNING_LIMIT_REACHED: (
        "Additional source-structure warnings were omitted."
    ),
}


@dataclass(frozen=True, slots=True)
class SourceStructureLimits:
    """Resource limits for one repository source-analysis pass."""

    timeout_seconds: int
    max_source_file_bytes: int
    max_structure_files: int
    max_source_symbols: int
    max_source_imports: int
    max_symbols_per_file: int
    max_imports_per_file: int
    max_imported_names_per_import: int
    max_warnings: int


@dataclass(frozen=True, slots=True)
class SourceSymbol:
    """One safe symbol declaration without its source body."""

    relative_path: str
    language: str
    kind: SourceSymbolKind
    name: str
    qualified_name: str
    start_line: int
    end_line: int
    parent_name: str | None
    parameter_count: int
    is_exported: bool
    is_public: bool


@dataclass(frozen=True, slots=True)
class ImportFinding:
    """One normalized import without its complete source statement."""

    relative_path: str
    language: str
    module: str
    imported_names: tuple[str, ...]
    import_kind: SourceImportKind
    is_relative: bool
    start_line: int


@dataclass(frozen=True, slots=True)
class SourceFileStructure:
    """Bounded structural counters for one supported source file."""

    relative_path: str
    language: str
    category: FileCategory
    line_count: int
    symbol_count: int
    import_count: int
    class_count: int
    function_count: int
    method_count: int
    parse_status: SourceParseStatus
    has_syntax_errors: bool


@dataclass(frozen=True, slots=True)
class LanguageFileCount:
    """Parsed or skipped supported-file count for one language."""

    language: str
    file_count: int


@dataclass(frozen=True, slots=True)
class CodeStructureSummary:
    """Repository-wide source-structure counters."""

    supported_source_file_count: int
    parsed_file_count: int
    skipped_file_count: int
    parse_error_file_count: int
    total_symbol_count: int
    total_function_count: int
    total_class_count: int
    total_method_count: int
    total_import_count: int
    language_file_counts: tuple[LanguageFileCount, ...]


@dataclass(frozen=True, slots=True)
class SourceStructureWarning:
    """A safe fixed warning without parser or source detail."""

    code: SourceStructureWarningCode
    relative_path: str | None
    message: str


@dataclass(frozen=True, slots=True)
class CodeStructureResult:
    """Deterministic supported-language source structure."""

    summary: CodeStructureSummary
    files: tuple[SourceFileStructure, ...]
    symbols: tuple[SourceSymbol, ...]
    imports: tuple[ImportFinding, ...]
    warnings: tuple[SourceStructureWarning, ...]


@dataclass(frozen=True, slots=True)
class ParsedSourceStructure:
    """Parser output before service-level limits and counters."""

    symbols: tuple[SourceSymbol, ...]
    imports: tuple[ImportFinding, ...]
    has_syntax_errors: bool
    parse_failed: bool = False
    skipped: bool = False
    symbols_truncated: bool = False
    imports_truncated: bool = False
