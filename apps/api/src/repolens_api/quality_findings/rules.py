"""Pure deterministic rules for repository quality findings."""

from dataclasses import dataclass
from pathlib import PurePosixPath

from repolens_api.code_structure.contracts import (
    CodeStructureResult,
    SourceParseStatus,
)
from repolens_api.inventory.contracts import (
    FileCategory,
    FileInventoryEntry,
    InventoryResult,
    ManifestFact,
)
from repolens_api.inventory.policy import documentation_kind, path_sort_key
from repolens_api.quality_findings.contracts import (
    QualityEvidence,
    QualityEvidenceKind,
    QualityFinding,
    QualityFindingCode,
)
from repolens_api.quality_findings.policy import (
    COMMUNITY_PATH_MARKERS,
    CONTAINER_NAMES,
    DEPENDENCY_AUTOMATION_PATHS,
    FINDING_TEXTS,
    IMPORT_DENSE_FILE_COUNT,
    LOCKFILE_NAMES,
    MANIFEST_LOCKFILE_NAMES,
    MANIFEST_NAMES,
    METHOD_DENSE_FILE_COUNT,
    OVERSIZED_SOURCE_FILE_BYTES,
    README_MIN_BYTES,
    README_MIN_NONEMPTY_LINES,
    ROOT_FILE_DENSITY_COUNT,
    SOURCE_CONCENTRATION_MIN_FILES,
    SOURCE_CONCENTRATION_MIN_SYMBOLS,
    SOURCE_CONCENTRATION_PER_MILLE,
    SPARSE_TEST_MIN_SOURCE_FILES,
    SPARSE_TEST_RATIO_PER_MILLE,
    STRUCTURE_SUCCESS_PER_MILLE,
    STRUCTURE_WARNING_HIGH_COUNT,
    SYMBOL_DENSE_FILE_COUNT,
    TEST_CONFIGURATION_NAMES,
    TEST_FRAMEWORK_NAMES,
)


@dataclass(frozen=True, slots=True)
class ReadmeSignals:
    """Bounded non-persisted README signals."""

    relative_path: str | None
    readable: bool
    byte_count: int
    nonempty_line_count: int
    heading_count: int
    code_fence_count: int
    link_count: int
    has_installation: bool
    has_usage: bool
    has_testing: bool


@dataclass(frozen=True, slots=True)
class AutomationSignals:
    """Bounded non-persisted CI text signals."""

    ci_paths: tuple[str, ...]
    readable_ci_count: int
    has_lint: bool
    has_test: bool
    has_build: bool


@dataclass(frozen=True, slots=True)
class QualityRuleInput:
    """Safe inputs consumed by pure quality rules."""

    inventory: InventoryResult
    files: tuple[FileInventoryEntry, ...]
    directories: tuple[str, ...]
    manifests: tuple[ManifestFact, ...]
    structure: CodeStructureResult
    readme: ReadmeSignals
    automation: AutomationSignals


def _evidence(kind: QualityEvidenceKind, value: int) -> QualityEvidence:
    return QualityEvidence(kind=kind, value=max(0, value))


def _finding(
    code: QualityFindingCode,
    *,
    evidence: tuple[QualityEvidence, ...] = (),
    related_paths: tuple[str, ...] = (),
) -> QualityFinding:
    text = FINDING_TEXTS[code]
    return QualityFinding(
        code=code,
        category=text.category,
        severity=text.severity,
        title=text.title,
        message=text.message,
        recommendation=text.recommendation,
        evidence=evidence,
        related_paths=related_paths,
    )


def evaluate_quality_rules(data: QualityRuleInput) -> tuple[QualityFinding, ...]:
    """Evaluate all Stage 5 rules without reading repository content."""
    findings = [
        *_documentation_findings(data),
        *_testing_findings(data),
        *_governance_findings(data),
        *_automation_findings(data),
        *_maintainability_findings(data),
        *_onboarding_findings(data),
    ]
    return tuple(findings)


def _important_paths(inventory: InventoryResult, kind: str) -> tuple[str, ...]:
    for group in inventory.important_files:
        if group.kind == kind:
            return group.paths
    return ()


def _documentation_findings(data: QualityRuleInput) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    readme = data.readme
    if readme.relative_path is None:
        findings.append(_finding(QualityFindingCode.README_MISSING))
    elif readme.readable:
        readme_evidence = (
            _evidence(QualityEvidenceKind.BYTE_COUNT, readme.byte_count),
            _evidence(QualityEvidenceKind.LINE_COUNT, readme.nonempty_line_count),
            _evidence(QualityEvidenceKind.HEADING_COUNT, readme.heading_count),
            _evidence(QualityEvidenceKind.CODE_FENCE_COUNT, readme.code_fence_count),
            _evidence(QualityEvidenceKind.LINK_COUNT, readme.link_count),
        )
        related = (readme.relative_path,)
        if (
            readme.byte_count < README_MIN_BYTES
            or readme.nonempty_line_count < README_MIN_NONEMPTY_LINES
        ):
            findings.append(
                _finding(
                    QualityFindingCode.README_TOO_SMALL,
                    evidence=readme_evidence,
                    related_paths=related,
                )
            )
        else:
            if not readme.has_installation:
                findings.append(
                    _finding(
                        QualityFindingCode.README_INSTALLATION_MISSING,
                        related_paths=related,
                    )
                )
            if not readme.has_usage:
                findings.append(
                    _finding(QualityFindingCode.README_USAGE_MISSING, related_paths=related)
                )
            if not readme.has_testing:
                findings.append(
                    _finding(QualityFindingCode.README_TESTING_MISSING, related_paths=related)
                )

    readme_complete = (
        readme.readable
        and readme.byte_count >= README_MIN_BYTES
        and readme.nonempty_line_count >= README_MIN_NONEMPTY_LINES
        and readme.has_installation
        and readme.has_usage
        and readme.has_testing
    )
    documentation_paths = tuple(
        sorted(
            {
                entry.relative_path
                for entry in data.files
                if (
                    entry.category is FileCategory.DOCUMENTATION
                    and documentation_kind(entry.name) != "readme"
                )
                or any(
                    marker in PurePosixPath(entry.relative_path).stem.casefold()
                    for marker in ("release-notes", "release_notes", "releasenotes")
                )
            },
            key=path_sort_key,
        )
    )
    docs_directory_count = sum(
        PurePosixPath(directory).name.casefold() in {"doc", "docs", "documentation"}
        for directory in data.directories
    )
    api_architecture_count = sum(
        any(marker in PurePosixPath(path).name.casefold() for marker in ("api", "architect"))
        for path in documentation_paths
    )
    positive_paths = (
        (readme.relative_path,) if readme_complete and readme.relative_path else ()
    ) + documentation_paths
    if positive_paths or docs_directory_count:
        findings.append(
            _finding(
                QualityFindingCode.DOCUMENTATION_PRESENT,
                evidence=(
                    _evidence(
                        QualityEvidenceKind.FILE_COUNT,
                        len(positive_paths) + docs_directory_count,
                    ),
                    _evidence(
                        QualityEvidenceKind.DOCUMENTATION_SIGNAL_COUNT,
                        api_architecture_count,
                    ),
                ),
                related_paths=positive_paths,
            )
        )
    return findings


def _testing_findings(data: QualityRuleInput) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    test_paths = tuple(
        sorted(
            {entry.relative_path for entry in data.files if entry.category is FileCategory.TEST},
            key=path_sort_key,
        )
    )
    source_count = sum(item.category is FileCategory.SOURCE for item in data.structure.files)
    test_count = len(test_paths)
    ratio = test_count * 1_000 // max(source_count, 1)
    ratio_evidence = (
        _evidence(QualityEvidenceKind.TEST_FILE_COUNT, test_count),
        _evidence(QualityEvidenceKind.SOURCE_FILE_COUNT, source_count),
        _evidence(QualityEvidenceKind.TEST_SOURCE_RATIO_PER_MILLE, ratio),
    )
    if source_count > 0 and test_count == 0:
        findings.append(_finding(QualityFindingCode.TESTS_MISSING, evidence=ratio_evidence))
    elif test_count > 0:
        findings.append(
            _finding(
                QualityFindingCode.TESTS_PRESENT,
                evidence=ratio_evidence,
                related_paths=test_paths,
            )
        )
        if source_count >= SPARSE_TEST_MIN_SOURCE_FILES and ratio < SPARSE_TEST_RATIO_PER_MILLE:
            findings.append(
                _finding(
                    QualityFindingCode.TESTS_SPARSE,
                    evidence=ratio_evidence,
                    related_paths=test_paths,
                )
            )
        if all(
            any(
                marker in {part.casefold() for part in PurePosixPath(path).parts}
                or marker in PurePosixPath(path).stem.casefold()
                for marker in ("demo", "example", "examples", "sample", "samples")
            )
            for path in test_paths
        ):
            findings.append(
                _finding(QualityFindingCode.EXAMPLE_ONLY_TESTS, related_paths=test_paths)
            )

    test_config_paths = tuple(
        sorted(
            {
                entry.relative_path
                for entry in data.files
                if PurePosixPath(entry.relative_path).name.casefold() in TEST_CONFIGURATION_NAMES
            },
            key=path_sort_key,
        )
    )
    has_manifest_test = any("has_test_script" in fact.metadata_flags for fact in data.manifests)
    if test_config_paths or has_manifest_test:
        findings.append(
            _finding(
                QualityFindingCode.TEST_CONFIGURATION_PRESENT,
                evidence=(
                    _evidence(
                        QualityEvidenceKind.FILE_COUNT,
                        len(test_config_paths) + int(has_manifest_test),
                    ),
                ),
                related_paths=test_config_paths,
            )
        )

    frameworks = {
        name.casefold()
        for fact in data.manifests
        for name in fact.names
        if name.casefold() in TEST_FRAMEWORK_NAMES
    }
    if len(frameworks) > 1:
        findings.append(
            _finding(
                QualityFindingCode.MULTIPLE_TEST_FRAMEWORKS_PRESENT,
                evidence=(_evidence(QualityEvidenceKind.FRAMEWORK_COUNT, len(frameworks)),),
            )
        )

    if test_count > 0 and data.automation.ci_paths:
        code = (
            QualityFindingCode.TEST_CI_INTEGRATION_PRESENT
            if data.automation.has_test
            else QualityFindingCode.TEST_CI_INTEGRATION_MISSING
        )
        findings.append(
            _finding(
                code,
                evidence=(
                    _evidence(QualityEvidenceKind.TEST_FILE_COUNT, test_count),
                    _evidence(
                        QualityEvidenceKind.CI_FILE_COUNT,
                        len(data.automation.ci_paths),
                    ),
                ),
                related_paths=(*test_paths, *data.automation.ci_paths),
            )
        )
    return findings


def _governance_findings(data: QualityRuleInput) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    for present_code, missing_code, kind in (
        (
            QualityFindingCode.LICENSE_PRESENT,
            QualityFindingCode.LICENSE_MISSING,
            "license",
        ),
        (
            QualityFindingCode.CONTRIBUTING_PRESENT,
            QualityFindingCode.CONTRIBUTING_MISSING,
            "contributing",
        ),
        (
            QualityFindingCode.SECURITY_POLICY_PRESENT,
            QualityFindingCode.SECURITY_POLICY_MISSING,
            "security",
        ),
    ):
        paths = _important_paths(data.inventory, kind)
        findings.append(_finding(present_code if paths else missing_code, related_paths=paths))

    community_paths = tuple(
        sorted(
            {
                entry.relative_path
                for entry in data.files
                if any(
                    marker in f"/{entry.relative_path.casefold()}"
                    for marker in COMMUNITY_PATH_MARKERS
                )
                or documentation_kind(PurePosixPath(entry.relative_path).name)
                in {"code_of_conduct", "changelog"}
            },
            key=path_sort_key,
        )
    )
    if community_paths:
        findings.append(
            _finding(
                QualityFindingCode.COMMUNITY_FILES_PRESENT,
                evidence=(
                    _evidence(
                        QualityEvidenceKind.COMMUNITY_FILE_COUNT,
                        len(community_paths),
                    ),
                ),
                related_paths=community_paths,
            )
        )
    return findings


def _automation_findings(data: QualityRuleInput) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    ci = data.automation
    if ci.ci_paths:
        findings.append(
            _finding(
                QualityFindingCode.CI_PRESENT,
                evidence=(_evidence(QualityEvidenceKind.CI_FILE_COUNT, len(ci.ci_paths)),),
                related_paths=ci.ci_paths,
            )
        )
        if not (ci.has_lint or ci.has_test or ci.has_build) and ci.readable_ci_count:
            findings.append(
                _finding(
                    QualityFindingCode.CI_QUALITY_CHECKS_MISSING,
                    related_paths=ci.ci_paths,
                )
            )
    else:
        findings.append(_finding(QualityFindingCode.CI_MISSING))

    dependency_paths = tuple(
        sorted(
            {
                entry.relative_path
                for entry in data.files
                if entry.relative_path.casefold() in DEPENDENCY_AUTOMATION_PATHS
            },
            key=path_sort_key,
        )
    )
    if dependency_paths:
        findings.append(
            _finding(
                QualityFindingCode.DEPENDENCY_UPDATE_AUTOMATION_PRESENT,
                related_paths=dependency_paths,
            )
        )

    container_paths = tuple(
        sorted(
            {
                entry.relative_path
                for entry in data.files
                if PurePosixPath(entry.relative_path).name.casefold() in CONTAINER_NAMES
                or PurePosixPath(entry.relative_path).name.casefold() == "dockerfile"
                or PurePosixPath(entry.relative_path).name.casefold().startswith("dockerfile.")
            },
            key=path_sort_key,
        )
    )
    if container_paths:
        findings.append(
            _finding(
                QualityFindingCode.CONTAINER_SETUP_PRESENT,
                related_paths=container_paths,
            )
        )
    return findings


def _maintainability_findings(data: QualityRuleInput) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    inventory_by_path = {entry.relative_path: entry for entry in data.files}
    for item in data.structure.files:
        entry = inventory_by_path.get(item.relative_path)
        if entry is not None and entry.size_bytes > OVERSIZED_SOURCE_FILE_BYTES:
            findings.append(
                _finding(
                    QualityFindingCode.OVERSIZED_SOURCE_FILE,
                    evidence=(_evidence(QualityEvidenceKind.BYTE_COUNT, entry.size_bytes),),
                    related_paths=(item.relative_path,),
                )
            )
        for code, kind, value, threshold in (
            (
                QualityFindingCode.SYMBOL_DENSE_FILE,
                QualityEvidenceKind.SYMBOL_COUNT,
                item.symbol_count,
                SYMBOL_DENSE_FILE_COUNT,
            ),
            (
                QualityFindingCode.IMPORT_DENSE_FILE,
                QualityEvidenceKind.IMPORT_COUNT,
                item.import_count,
                IMPORT_DENSE_FILE_COUNT,
            ),
            (
                QualityFindingCode.METHOD_DENSE_FILE,
                QualityEvidenceKind.METHOD_COUNT,
                item.method_count,
                METHOD_DENSE_FILE_COUNT,
            ),
        ):
            if value > threshold:
                findings.append(
                    _finding(
                        code,
                        evidence=(_evidence(kind, value),),
                        related_paths=(item.relative_path,),
                    )
                )

    symbol_files = [item for item in data.structure.files if item.symbol_count > 0]
    total_symbols = sum(item.symbol_count for item in symbol_files)
    if (
        len(symbol_files) >= SOURCE_CONCENTRATION_MIN_FILES
        and total_symbols >= SOURCE_CONCENTRATION_MIN_SYMBOLS
    ):
        dominant = sorted(
            symbol_files,
            key=lambda item: (
                -item.symbol_count,
                *path_sort_key(item.relative_path),
            ),
        )[0]
        concentration = dominant.symbol_count * 1_000 // total_symbols
        if concentration >= SOURCE_CONCENTRATION_PER_MILLE:
            findings.append(
                _finding(
                    QualityFindingCode.SOURCE_CONCENTRATION_HIGH,
                    evidence=(
                        _evidence(QualityEvidenceKind.SYMBOL_COUNT, dominant.symbol_count),
                        _evidence(
                            QualityEvidenceKind.CONCENTRATION_PER_MILLE,
                            concentration,
                        ),
                    ),
                    related_paths=(dominant.relative_path,),
                )
            )

    parse_errors = sum(
        item.parse_status in {SourceParseStatus.FAILED, SourceParseStatus.PARTIAL}
        or item.has_syntax_errors
        for item in data.structure.files
    )
    if parse_errors:
        findings.append(
            _finding(
                QualityFindingCode.SOURCE_PARSE_ERRORS_PRESENT,
                evidence=(_evidence(QualityEvidenceKind.PARSE_ERROR_FILE_COUNT, parse_errors),),
                related_paths=tuple(
                    item.relative_path
                    for item in data.structure.files
                    if item.parse_status in {SourceParseStatus.FAILED, SourceParseStatus.PARTIAL}
                    or item.has_syntax_errors
                ),
            )
        )

    warning_count = len(data.structure.warnings)
    if warning_count >= STRUCTURE_WARNING_HIGH_COUNT:
        findings.append(
            _finding(
                QualityFindingCode.STRUCTURE_WARNINGS_HIGH,
                evidence=(_evidence(QualityEvidenceKind.STRUCTURE_WARNING_COUNT, warning_count),),
            )
        )

    supported = data.structure.summary.supported_source_file_count
    parsed = data.structure.summary.parsed_file_count
    success_ratio = parsed * 1_000 // max(supported, 1)
    if supported and success_ratio >= STRUCTURE_SUCCESS_PER_MILLE:
        findings.append(
            _finding(
                QualityFindingCode.STRUCTURE_ANALYSIS_SUCCESSFUL,
                evidence=(
                    _evidence(QualityEvidenceKind.PARSED_FILE_COUNT, parsed),
                    _evidence(
                        QualityEvidenceKind.SUPPORTED_SOURCE_FILE_COUNT,
                        supported,
                    ),
                ),
            )
        )

    root_paths = tuple(
        sorted(
            {
                entry.relative_path
                for entry in data.files
                if len(PurePosixPath(entry.relative_path).parts) == 1
            },
            key=path_sort_key,
        )
    )
    if len(root_paths) >= ROOT_FILE_DENSITY_COUNT:
        findings.append(
            _finding(
                QualityFindingCode.ROOT_FILE_DENSITY_HIGH,
                evidence=(_evidence(QualityEvidenceKind.ROOT_FILE_COUNT, len(root_paths)),),
                related_paths=root_paths,
            )
        )
    return findings


def _onboarding_findings(data: QualityRuleInput) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    entry_paths = tuple(
        sorted(
            {item.relative_path for item in data.inventory.entry_points},
            key=path_sort_key,
        )
    )
    manifest_paths = tuple(
        sorted(
            {
                entry.relative_path
                for entry in data.files
                if PurePosixPath(entry.relative_path).name.casefold() in MANIFEST_NAMES
            },
            key=path_sort_key,
        )
    )
    if entry_paths:
        findings.append(
            _finding(
                QualityFindingCode.ENTRY_POINTS_PRESENT,
                evidence=(_evidence(QualityEvidenceKind.ENTRY_POINT_COUNT, len(entry_paths)),),
                related_paths=entry_paths,
            )
        )
    elif manifest_paths:
        findings.append(
            _finding(
                QualityFindingCode.ENTRY_POINT_MISSING,
                related_paths=manifest_paths,
            )
        )

    environment_paths = _important_paths(data.inventory, "environment_example")
    if environment_paths:
        findings.append(
            _finding(
                QualityFindingCode.ENVIRONMENT_EXAMPLE_PRESENT,
                related_paths=environment_paths,
            )
        )

    lockfile_paths = tuple(
        sorted(
            {
                entry.relative_path
                for entry in data.files
                if PurePosixPath(entry.relative_path).name.casefold() in LOCKFILE_NAMES
            },
            key=path_sort_key,
        )
    )
    file_names = {PurePosixPath(entry.relative_path).name.casefold() for entry in data.files}
    expected_lock_groups = tuple(
        lock_names
        for manifest_name, lock_names in MANIFEST_LOCKFILE_NAMES.items()
        if manifest_name in file_names
    )
    all_manifest_ecosystems_locked = bool(expected_lock_groups) and all(
        not lock_names.isdisjoint(file_names) for lock_names in expected_lock_groups
    )
    if lockfile_paths and all_manifest_ecosystems_locked:
        findings.append(_finding(QualityFindingCode.LOCKFILE_PRESENT, related_paths=lockfile_paths))
    elif expected_lock_groups:
        findings.append(_finding(QualityFindingCode.LOCKFILE_MISSING, related_paths=manifest_paths))

    contributing_paths = _important_paths(data.inventory, "contributing")
    if (data.readme.readable and data.readme.has_installation) or contributing_paths:
        findings.append(
            _finding(
                QualityFindingCode.DEVELOPMENT_SETUP_PRESENT,
                related_paths=tuple(
                    path
                    for path in (data.readme.relative_path, *contributing_paths)
                    if path is not None
                ),
            )
        )
    return findings
