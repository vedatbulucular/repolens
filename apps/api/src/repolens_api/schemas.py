"""HTTP request and response models exposed by the API."""

from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict


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
    """Strict schema for supported persisted inventory payloads."""

    repository_summary: RepositorySummaryResponse
    languages: list[LanguageStatisticResponse]
    important_files: list[ImportantFileGroupResponse]
    technologies: list[TechnologyFindingResponse]
    entry_points: list[EntryPointFindingResponse]
    warnings: list[InventoryWarningResponse]


class AnalysisResultResponse(InventoryPayloadResponse):
    """Completed analysis result with lifecycle and repository metadata."""

    analysis_id: UUID
    result_schema_version: int
    repository: RepositoryResponse
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
