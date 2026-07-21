"""Validated state transitions for analysis jobs."""

from datetime import UTC, datetime

from repolens_api.models import Analysis, AnalysisStatus

ALLOWED_TRANSITIONS: dict[AnalysisStatus, frozenset[AnalysisStatus]] = {
    AnalysisStatus.QUEUED: frozenset({AnalysisStatus.PROCESSING, AnalysisStatus.FAILED}),
    AnalysisStatus.PROCESSING: frozenset({AnalysisStatus.COMPLETED, AnalysisStatus.FAILED}),
    AnalysisStatus.COMPLETED: frozenset(),
    AnalysisStatus.FAILED: frozenset(),
}


class InvalidStatusTransition(ValueError):
    """Raised when an analysis lifecycle transition is not allowed."""


def transition_analysis(
    analysis: Analysis,
    target: AnalysisStatus,
    *,
    error_message: str | None = None,
    error_code: str | None = None,
    occurred_at: datetime | None = None,
) -> None:
    """Apply one allowed lifecycle transition and its timestamps."""
    if target not in ALLOWED_TRANSITIONS[analysis.status]:
        raise InvalidStatusTransition(f"{analysis.status.value} -> {target.value}")

    timestamp = occurred_at or datetime.now(UTC)
    analysis.status = target

    if target is AnalysisStatus.PROCESSING:
        analysis.started_at = timestamp
        analysis.error_message = None
        analysis.error_code = None
    elif target is AnalysisStatus.COMPLETED:
        analysis.completed_at = timestamp
        analysis.error_message = None
        analysis.error_code = None
        analysis.processing_token = None
    elif target is AnalysisStatus.FAILED:
        analysis.completed_at = timestamp
        analysis.error_message = error_message or "Analysis processing failed."
        analysis.error_code = error_code
        analysis.processing_token = None
