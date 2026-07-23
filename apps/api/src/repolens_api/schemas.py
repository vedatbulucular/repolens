"""HTTP request and response models exposed by the API."""

from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, model_validator

from repolens_api.code_structure.contracts import (
    SOURCE_STRUCTURE_WARNING_MESSAGES,
    SourceStructureWarningCode,
)


def _relative_path(value: str) -> str:
    posix_path = PurePosixPath(value)
    if (
        not value
        or posix_path.is_absolute()
        or PureWindowsPath(value).is_absolute()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in posix_path.parts)
    ):
        raise ValueError("invalid relative path")
    return value


RelativePath = Annotated[str, AfterValidator(_relative_path)]


class HealthResponse(BaseModel):
    """Successful health-check response."""

    status: Literal["ok"]
    service: str
    version: str


class AnalysisCreateRequest(BaseModel):
    """Request body for a new analysis job."""

    repository_url: str


class RepositoryResponse(BaseModel):
    """Canonical repository identity returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    canonical_url: str
    owner: str
    name: str
    default_branch: str | None


class AnalysisResponse(BaseModel):
    """Current state of an analysis job."""

    id: UUID
    status: Literal["queued", "processing", "completed", "failed"]
    requested_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    error_message: str | None
    error_code: str | None
    repository: RepositoryResponse


class InventoryPayloadModel(BaseModel):
    """Strict base for persisted inventory payload components."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DirectoryFileCountResponse(InventoryPayloadModel):
    """Recursive file count for one repository directory."""

    relative_path: RelativePath
    file_count: int


class RepositorySummaryResponse(InventoryPayloadModel):
    """Typed aggregate inventory metadata."""

    regular_file_count: int
    analyzed_directory_count: int
    total_file_bytes: int
    max_directory_depth: int
    top_level_directories: list[RelativePath]
    directories_by_file_count: list[DirectoryFileCountResponse]
    ignored_directory_count: int
    binary_file_count: int
    unreadable_file_count: int
    skipped_content_file_count: int
    sensitive_file_count: int


class LanguageStatisticResponse(InventoryPayloadModel):
    """Typed byte-weighted language statistic."""

    name: str
    file_count: int
    total_bytes: int
    percentage: float


class ImportantFileGroupResponse(InventoryPayloadModel):
    """Typed important-file evidence group."""

    kind: str
    count: int
    paths: list[RelativePath]
    truncated: bool


class TechnologyEvidenceResponse(InventoryPayloadModel):
    """Typed evidence for one technology finding."""

    evidence_type: str
    relative_path: RelativePath


class TechnologyFindingResponse(InventoryPayloadModel):
    """Typed deduplicated technology finding."""

    name: str
    category: str
    confidence: Literal["high", "medium"]
    evidence: list[TechnologyEvidenceResponse]
    evidence_truncated: bool


class EntryPointFindingResponse(InventoryPayloadModel):
    """Typed conservative entry-point finding."""

    kind: str
    relative_path: RelativePath
    confidence: Literal["high", "medium"]
    evidence_type: str


class InventoryWarningResponse(InventoryPayloadModel):
    """Typed safe inventory warning."""

    code: str
    relative_path: RelativePath | None
    message: str


class InventoryPayloadResponse(InventoryPayloadModel):
    """Strict schema for persisted version 1 inventory payloads."""

    repository_summary: RepositorySummaryResponse
    languages: list[LanguageStatisticResponse]
    important_files: list[ImportantFileGroupResponse]
    technologies: list[TechnologyFindingResponse]
    entry_points: list[EntryPointFindingResponse]
    warnings: list[InventoryWarningResponse]


class SourceLanguageFileCountResponse(InventoryPayloadModel):
    """Supported source-file count for one language."""

    language: str
    file_count: int


class CodeStructureSummaryResponse(InventoryPayloadModel):
    """Typed repository-wide source-structure counters."""

    supported_source_file_count: int
    parsed_file_count: int
    skipped_file_count: int
    parse_error_file_count: int
    total_symbol_count: int
    total_function_count: int
    total_class_count: int
    total_method_count: int
    total_import_count: int
    language_file_counts: list[SourceLanguageFileCountResponse]


class SourceFileStructureResponse(InventoryPayloadModel):
    """Typed structural counters for one supported source file."""

    relative_path: RelativePath
    language: Literal["Python", "TypeScript", "JavaScript"]
    category: str
    line_count: int
    symbol_count: int
    import_count: int
    class_count: int
    function_count: int
    method_count: int
    parse_status: Literal["parsed", "partial", "failed", "skipped"]
    has_syntax_errors: bool


class SourceSymbolResponse(InventoryPayloadModel):
    """Typed source declaration without its body or literal values."""

    relative_path: RelativePath
    language: Literal["Python", "TypeScript", "JavaScript"]
    kind: Literal["function", "async_function", "class", "method", "async_method"]
    name: str
    qualified_name: str
    start_line: int
    end_line: int
    parent_name: str | None
    parameter_count: int
    is_exported: bool
    is_public: bool


class SourceImportResponse(InventoryPayloadModel):
    """Typed normalized import without its complete source statement."""

    relative_path: RelativePath
    language: Literal["Python", "TypeScript", "JavaScript"]
    module: str
    imported_names: list[str]
    import_kind: Literal[
        "python_import",
        "python_from_import",
        "ecmascript_import",
        "commonjs_require",
    ]
    is_relative: bool
    start_line: int


class SourceStructureWarningResponse(InventoryPayloadModel):
    """Typed safe source-analysis warning."""

    code: Literal[
        "source_parse_failed",
        "source_syntax_error",
        "unsupported_source_encoding",
        "source_file_too_large",
        "source_file_unreadable",
        "source_symbols_truncated",
        "source_imports_truncated",
        "structure_warning_limit_reached",
    ]
    relative_path: RelativePath | None
    message: str

    @model_validator(mode="after")
    def validate_fixed_message(self) -> "SourceStructureWarningResponse":
        """Reject stored parser diagnostics or other non-contract warning text."""
        code = SourceStructureWarningCode(self.code)
        if self.message != SOURCE_STRUCTURE_WARNING_MESSAGES[code]:
            raise ValueError("invalid source-structure warning message")
        return self


class CodeStructureResponse(InventoryPayloadModel):
    """Strict persisted source-structure payload."""

    summary: CodeStructureSummaryResponse
    files: list[SourceFileStructureResponse]
    symbols: list[SourceSymbolResponse]
    imports: list[SourceImportResponse]
    warnings: list[SourceStructureWarningResponse]


class InventoryPayloadV2Response(InventoryPayloadResponse):
    """Strict schema for version 2 inventory and source structure."""

    code_structure: CodeStructureResponse


class AnalysisResultResponse(InventoryPayloadResponse):
    """Completed analysis result with lifecycle and repository metadata."""

    analysis_id: UUID
    result_schema_version: int
    repository: RepositoryResponse
    code_structure: CodeStructureResponse | None = None
    requested_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None


class ProblemDetail(BaseModel):
    """Machine-readable API error response."""

    type: str
    title: str
    status: int
    detail: str
    error_code: str | None = None
