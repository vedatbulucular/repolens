"""Immutable contracts for deterministic repository quality findings."""

from dataclasses import dataclass
from enum import StrEnum


class QualityCategory(StrEnum):
    """Stable finding categories."""

    DOCUMENTATION = "documentation"
    TESTING = "testing"
    PROJECT_GOVERNANCE = "project_governance"
    AUTOMATION = "automation"
    MAINTAINABILITY = "maintainability"
    ONBOARDING = "onboarding"


class QualitySeverity(StrEnum):
    """Finding importance without a numeric score."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class QualityFindingCode(StrEnum):
    """Stable deterministic quality rule codes."""

    README_MISSING = "readme_missing"
    README_TOO_SMALL = "readme_too_small"
    README_INSTALLATION_MISSING = "readme_installation_missing"
    README_USAGE_MISSING = "readme_usage_missing"
    README_TESTING_MISSING = "readme_testing_missing"
    DOCUMENTATION_PRESENT = "documentation_present"
    TESTS_MISSING = "tests_missing"
    TESTS_SPARSE = "tests_sparse"
    TESTS_PRESENT = "tests_present"
    TEST_CONFIGURATION_PRESENT = "test_configuration_present"
    MULTIPLE_TEST_FRAMEWORKS_PRESENT = "multiple_test_frameworks_present"
    EXAMPLE_ONLY_TESTS = "example_only_tests"
    TEST_CI_INTEGRATION_MISSING = "test_ci_integration_missing"
    TEST_CI_INTEGRATION_PRESENT = "test_ci_integration_present"
    LICENSE_MISSING = "license_missing"
    LICENSE_PRESENT = "license_present"
    CONTRIBUTING_MISSING = "contributing_missing"
    CONTRIBUTING_PRESENT = "contributing_present"
    SECURITY_POLICY_MISSING = "security_policy_missing"
    SECURITY_POLICY_PRESENT = "security_policy_present"
    COMMUNITY_FILES_PRESENT = "community_files_present"
    CI_MISSING = "ci_missing"
    CI_PRESENT = "ci_present"
    CI_QUALITY_CHECKS_MISSING = "ci_quality_checks_missing"
    DEPENDENCY_UPDATE_AUTOMATION_PRESENT = "dependency_update_automation_present"
    CONTAINER_SETUP_PRESENT = "container_setup_present"
    OVERSIZED_SOURCE_FILE = "oversized_source_file"
    SYMBOL_DENSE_FILE = "symbol_dense_file"
    IMPORT_DENSE_FILE = "import_dense_file"
    METHOD_DENSE_FILE = "method_dense_file"
    SOURCE_CONCENTRATION_HIGH = "source_concentration_high"
    SOURCE_PARSE_ERRORS_PRESENT = "source_parse_errors_present"
    STRUCTURE_WARNINGS_HIGH = "structure_warnings_high"
    STRUCTURE_ANALYSIS_SUCCESSFUL = "structure_analysis_successful"
    ROOT_FILE_DENSITY_HIGH = "root_file_density_high"
    ENTRY_POINT_MISSING = "entry_point_missing"
    ENTRY_POINTS_PRESENT = "entry_points_present"
    ENVIRONMENT_EXAMPLE_PRESENT = "environment_example_present"
    LOCKFILE_MISSING = "lockfile_missing"
    LOCKFILE_PRESENT = "lockfile_present"
    DEVELOPMENT_SETUP_PRESENT = "development_setup_present"


class QualityEvidenceKind(StrEnum):
    """Allowlisted numeric evidence keys."""

    FILE_COUNT = "file_count"
    BYTE_COUNT = "byte_count"
    LINE_COUNT = "line_count"
    HEADING_COUNT = "heading_count"
    CODE_FENCE_COUNT = "code_fence_count"
    LINK_COUNT = "link_count"
    DOCUMENTATION_SIGNAL_COUNT = "documentation_signal_count"
    SOURCE_FILE_COUNT = "source_file_count"
    TEST_FILE_COUNT = "test_file_count"
    TEST_SOURCE_RATIO_PER_MILLE = "test_source_ratio_per_mille"
    FRAMEWORK_COUNT = "framework_count"
    CI_FILE_COUNT = "ci_file_count"
    COMMUNITY_FILE_COUNT = "community_file_count"
    SYMBOL_COUNT = "symbol_count"
    IMPORT_COUNT = "import_count"
    METHOD_COUNT = "method_count"
    CONCENTRATION_PER_MILLE = "concentration_per_mille"
    PARSE_ERROR_FILE_COUNT = "parse_error_file_count"
    STRUCTURE_WARNING_COUNT = "structure_warning_count"
    PARSED_FILE_COUNT = "parsed_file_count"
    SUPPORTED_SOURCE_FILE_COUNT = "supported_source_file_count"
    ENTRY_POINT_COUNT = "entry_point_count"
    ROOT_FILE_COUNT = "root_file_count"


class QualityWarningCode(StrEnum):
    """Safe non-fatal quality-analysis warning codes."""

    QUALITY_DOCUMENT_UNREADABLE = "quality_document_unreadable"
    QUALITY_DOCUMENT_TOO_LARGE = "quality_document_too_large"
    QUALITY_DOCUMENT_UNSUPPORTED_ENCODING = "quality_document_unsupported_encoding"
    QUALITY_FINDINGS_TRUNCATED = "quality_findings_truncated"
    QUALITY_WARNING_LIMIT_REACHED = "quality_warning_limit_reached"


QUALITY_WARNING_MESSAGES: dict[QualityWarningCode, str] = {
    QualityWarningCode.QUALITY_DOCUMENT_UNREADABLE: (
        "A quality-analysis document could not be read safely."
    ),
    QualityWarningCode.QUALITY_DOCUMENT_TOO_LARGE: (
        "A quality-analysis document exceeds the allowed read size."
    ),
    QualityWarningCode.QUALITY_DOCUMENT_UNSUPPORTED_ENCODING: (
        "A quality-analysis document uses an unsupported encoding or contains binary data."
    ),
    QualityWarningCode.QUALITY_FINDINGS_TRUNCATED: ("Additional quality finding data was omitted."),
    QualityWarningCode.QUALITY_WARNING_LIMIT_REACHED: (
        "Additional quality-analysis warnings were omitted."
    ),
}


@dataclass(frozen=True, slots=True)
class QualityLimits:
    """Resource limits for one quality-analysis pass."""

    timeout_seconds: int
    max_findings: int
    max_related_paths: int
    max_evidence_items: int
    max_document_read_bytes: int


@dataclass(frozen=True, slots=True)
class QualityEvidence:
    """One bounded numeric fact supporting a finding."""

    kind: QualityEvidenceKind
    value: int


@dataclass(frozen=True, slots=True)
class QualityFinding:
    """One fixed-text finding supported by safe evidence."""

    code: QualityFindingCode
    category: QualityCategory
    severity: QualitySeverity
    title: str
    message: str
    recommendation: str
    evidence: tuple[QualityEvidence, ...]
    related_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QualityCategoryCount:
    """Finding count for one stable category."""

    category: QualityCategory
    count: int


@dataclass(frozen=True, slots=True)
class QualitySummary:
    """Repository-wide finding counters without a score."""

    total_finding_count: int
    high_count: int
    medium_count: int
    low_count: int
    info_count: int
    category_counts: tuple[QualityCategoryCount, ...]
    positive_signal_count: int
    improvement_finding_count: int


@dataclass(frozen=True, slots=True)
class QualityWarning:
    """A fixed warning without document or exception detail."""

    code: QualityWarningCode
    relative_path: str | None
    message: str


@dataclass(frozen=True, slots=True)
class QualityFindingsResult:
    """Deterministic quality findings, summary, and safe warnings."""

    summary: QualitySummary
    findings: tuple[QualityFinding, ...]
    warnings: tuple[QualityWarning, ...]
