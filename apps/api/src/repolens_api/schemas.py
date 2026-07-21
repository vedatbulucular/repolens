"""HTTP request and response models exposed by the API."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict


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


class ProblemDetail(BaseModel):
    """Machine-readable API error response."""

    type: str
    title: str
    status: int
    detail: str
