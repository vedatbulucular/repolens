"""Safe fatal failures for repository quality analysis."""

from enum import StrEnum


class QualityAnalysisErrorCode(StrEnum):
    """Machine-readable fatal quality-analysis classifications."""

    QUALITY_ANALYSIS_FAILED = "quality_analysis_failed"
    QUALITY_ANALYSIS_TIMEOUT = "quality_analysis_timeout"
    QUALITY_ANALYSIS_LIMIT_EXCEEDED = "quality_analysis_limit_exceeded"
    UNSAFE_QUALITY_PATH = "unsafe_quality_path"


class QualityAnalysisError(Exception):
    """Base fatal quality-analysis error with a fixed public message."""

    code = QualityAnalysisErrorCode.QUALITY_ANALYSIS_FAILED
    public_message = "Repository quality analysis failed."

    def __init__(self) -> None:
        super().__init__(self.public_message)


class QualityAnalysisFailed(QualityAnalysisError):
    """Classify an unexpected fatal quality-analysis failure."""


class QualityAnalysisTimeout(QualityAnalysisError):
    """Stop quality analysis after its monotonic deadline."""

    code = QualityAnalysisErrorCode.QUALITY_ANALYSIS_TIMEOUT
    public_message = "Repository quality analysis exceeded the allowed time."


class QualityAnalysisLimitExceeded(QualityAnalysisError):
    """Reject an unsafe quality-analysis workload."""

    code = QualityAnalysisErrorCode.QUALITY_ANALYSIS_LIMIT_EXCEEDED
    public_message = "Repository quality analysis exceeds an allowed limit."


class UnsafeQualityPath(QualityAnalysisError):
    """Reject an unsafe or changed quality-analysis path."""

    code = QualityAnalysisErrorCode.UNSAFE_QUALITY_PATH
    public_message = "Repository quality analysis encountered an unsafe path."
