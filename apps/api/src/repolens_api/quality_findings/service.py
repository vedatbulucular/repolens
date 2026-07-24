"""Bounded orchestration for deterministic repository quality findings."""

import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from repolens_api.code_structure.contracts import CodeStructureResult
from repolens_api.inventory.content import SafeContentReader
from repolens_api.inventory.contracts import (
    ContentStatus,
    FileInventoryEntry,
    InventoryResult,
    ManifestFact,
)
from repolens_api.inventory.errors import UnsafeRepositoryPath
from repolens_api.inventory.policy import path_sort_key
from repolens_api.quality_findings.contracts import (
    QUALITY_WARNING_MESSAGES,
    QualityCategoryCount,
    QualityFinding,
    QualityFindingsResult,
    QualityLimits,
    QualitySeverity,
    QualitySummary,
    QualityWarning,
    QualityWarningCode,
)
from repolens_api.quality_findings.errors import (
    QualityAnalysisError,
    QualityAnalysisFailed,
    QualityAnalysisLimitExceeded,
    QualityAnalysisTimeout,
    UnsafeQualityPath,
)
from repolens_api.quality_findings.policy import (
    CI_BUILD_PATTERN,
    CI_COMMAND_LINE_PATTERN,
    CI_LINT_PATTERN,
    CI_LIST_COMMAND_PATTERN,
    CI_TEST_PATTERN,
    FINDING_TEXTS,
    INSTALLATION_HEADINGS,
    MARKDOWN_HEADING_PATTERN,
    MARKDOWN_LINK_PATTERN,
    POSITIVE_FINDING_CODES,
    TESTING_HEADINGS,
    USAGE_HEADINGS,
    is_ci_path,
    normalized_heading,
    validate_quality_path,
)
from repolens_api.quality_findings.rules import (
    AutomationSignals,
    QualityRuleInput,
    ReadmeSignals,
    evaluate_quality_rules,
)


class QualityFindingsService:
    """Produce safe findings from inventory and source-structure facts."""

    def __init__(
        self,
        limits: QualityLimits,
        *,
        content_reader: SafeContentReader,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits = limits
        self._content_reader = content_reader
        self._clock = clock

    def analyze(
        self,
        repository_root: Path,
        *,
        inventory: InventoryResult,
        files: tuple[FileInventoryEntry, ...],
        directories: tuple[str, ...],
        manifests: tuple[ManifestFact, ...],
        structure: CodeStructureResult,
    ) -> QualityFindingsResult:
        """Return deterministic bounded findings or a safe fatal error."""
        try:
            if any(
                limit <= 0
                for limit in (
                    self._limits.timeout_seconds,
                    self._limits.max_findings,
                    self._limits.max_related_paths,
                    self._limits.max_evidence_items,
                    self._limits.max_document_read_bytes,
                )
            ):
                raise QualityAnalysisLimitExceeded
            deadline = self._clock() + self._limits.timeout_seconds
            self._check_deadline(deadline)
            readme, readme_warnings = self._read_readme(repository_root, files)
            self._check_deadline(deadline)
            automation, ci_warnings = self._read_ci(repository_root, files, deadline)
            self._check_deadline(deadline)
            raw_findings = evaluate_quality_rules(
                QualityRuleInput(
                    inventory=inventory,
                    files=files,
                    directories=directories,
                    manifests=manifests,
                    structure=structure,
                    readme=readme,
                    automation=automation,
                )
            )
            findings, truncated = self._bounded_findings(raw_findings)
            warnings = [*readme_warnings, *ci_warnings]
            if truncated:
                warnings.append(self._warning(QualityWarningCode.QUALITY_FINDINGS_TRUNCATED, None))
            self._check_deadline(deadline)
            return QualityFindingsResult(
                summary=self._summary(findings),
                findings=findings,
                warnings=self._bounded_warnings(warnings),
            )
        except QualityAnalysisError:
            raise
        except UnsafeRepositoryPath:
            raise UnsafeQualityPath from None
        except ValueError:
            raise UnsafeQualityPath from None
        except Exception:
            raise QualityAnalysisFailed from None

    def _read_readme(
        self,
        repository_root: Path,
        files: tuple[FileInventoryEntry, ...],
    ) -> tuple[ReadmeSignals, tuple[QualityWarning, ...]]:
        candidates = sorted(
            (
                entry
                for entry in files
                if PurePosixPath(entry.relative_path).name.casefold().startswith("readme")
            ),
            key=lambda entry: (
                len(PurePosixPath(entry.relative_path).parts),
                *path_sort_key(entry.relative_path),
            ),
        )
        if not candidates:
            return self._empty_readme(), ()
        entry = candidates[0]
        text, warning = self._read_document(repository_root, entry)
        if text is None:
            return (
                ReadmeSignals(
                    relative_path=entry.relative_path,
                    readable=False,
                    byte_count=entry.size_bytes,
                    nonempty_line_count=0,
                    heading_count=0,
                    code_fence_count=0,
                    link_count=0,
                    has_installation=False,
                    has_usage=False,
                    has_testing=False,
                ),
                (warning,) if warning is not None else (),
            )

        headings: set[str] = set()
        nonempty_lines = 0
        fence_count = 0
        link_count = 0
        in_fence = False
        in_comment = False
        for line in text.splitlines():
            stripped = line.strip()
            if "<!--" in stripped:
                in_comment = True
            if in_comment:
                if "-->" in stripped:
                    in_comment = False
                continue
            if stripped.startswith(("```", "~~~")):
                if not in_fence:
                    fence_count += 1
                in_fence = not in_fence
                continue
            if not stripped:
                continue
            nonempty_lines += 1
            if in_fence:
                continue
            match = MARKDOWN_HEADING_PATTERN.match(line)
            if match is not None:
                headings.add(normalized_heading(match.group(1)))
            link_count += len(MARKDOWN_LINK_PATTERN.findall(line))

        return (
            ReadmeSignals(
                relative_path=entry.relative_path,
                readable=True,
                byte_count=entry.size_bytes,
                nonempty_line_count=nonempty_lines,
                heading_count=len(headings),
                code_fence_count=fence_count,
                link_count=link_count,
                has_installation=self._has_heading(headings, INSTALLATION_HEADINGS),
                has_usage=self._has_heading(headings, USAGE_HEADINGS),
                has_testing=self._has_heading(headings, TESTING_HEADINGS),
            ),
            (),
        )

    def _read_ci(
        self,
        repository_root: Path,
        files: tuple[FileInventoryEntry, ...],
        deadline: float,
    ) -> tuple[AutomationSignals, tuple[QualityWarning, ...]]:
        candidates = tuple(
            sorted(
                (entry for entry in files if is_ci_path(entry.relative_path)),
                key=lambda entry: path_sort_key(entry.relative_path),
            )
        )
        warnings: list[QualityWarning] = []
        readable_count = 0
        has_lint = False
        has_test = False
        has_build = False
        for entry in candidates:
            self._check_deadline(deadline)
            text, warning = self._read_document(repository_root, entry)
            if warning is not None:
                warnings.append(warning)
            if text is None:
                continue
            readable_count += 1
            signal_text = self._ci_signal_text(text)
            has_lint = has_lint or CI_LINT_PATTERN.search(signal_text) is not None
            has_test = has_test or CI_TEST_PATTERN.search(signal_text) is not None
            has_build = has_build or CI_BUILD_PATTERN.search(signal_text) is not None
        return (
            AutomationSignals(
                ci_paths=tuple(entry.relative_path for entry in candidates),
                readable_ci_count=readable_count,
                has_lint=has_lint,
                has_test=has_test,
                has_build=has_build,
            ),
            tuple(warnings),
        )

    def _read_document(
        self,
        repository_root: Path,
        entry: FileInventoryEntry,
    ) -> tuple[str | None, QualityWarning | None]:
        if entry.content_status is ContentStatus.SENSITIVE:
            return None, None
        if entry.size_bytes > self._limits.max_document_read_bytes:
            return (
                None,
                self._warning(
                    QualityWarningCode.QUALITY_DOCUMENT_TOO_LARGE,
                    entry.relative_path,
                ),
            )
        read = self._content_reader.read_text(
            repository_root,
            entry.relative_path,
            expected_size=entry.size_bytes,
            max_bytes=self._limits.max_document_read_bytes,
        )
        if read.text is not None:
            return read.text, None
        code = {
            ContentStatus.TOO_LARGE: QualityWarningCode.QUALITY_DOCUMENT_TOO_LARGE,
            ContentStatus.UNREADABLE: QualityWarningCode.QUALITY_DOCUMENT_UNREADABLE,
        }.get(
            read.content_status,
            QualityWarningCode.QUALITY_DOCUMENT_UNSUPPORTED_ENCODING,
        )
        return None, self._warning(code, entry.relative_path)

    def _bounded_findings(
        self,
        findings: tuple[QualityFinding, ...],
    ) -> tuple[tuple[QualityFinding, ...], bool]:
        normalized: dict[tuple[object, ...], QualityFinding] = {}
        truncated = False
        for finding in findings:
            expected = FINDING_TEXTS[finding.code]
            if (
                finding.category is not expected.category
                or finding.severity is not expected.severity
                or finding.title != expected.title
                or finding.message != expected.message
                or finding.recommendation != expected.recommendation
            ):
                raise QualityAnalysisFailed
            paths = tuple(
                sorted(
                    {validate_quality_path(path) for path in finding.related_paths},
                    key=path_sort_key,
                )
            )
            if any(
                not isinstance(item.value, int) or isinstance(item.value, bool) or item.value < 0
                for item in finding.evidence
            ):
                raise QualityAnalysisFailed
            evidence = tuple(
                sorted(
                    set(finding.evidence),
                    key=lambda item: (item.kind.value, item.value),
                )
            )
            if len(paths) > self._limits.max_related_paths:
                paths = paths[: self._limits.max_related_paths]
                truncated = True
            if len(evidence) > self._limits.max_evidence_items:
                evidence = evidence[: self._limits.max_evidence_items]
                truncated = True
            item = QualityFinding(
                code=finding.code,
                category=finding.category,
                severity=finding.severity,
                title=finding.title,
                message=finding.message,
                recommendation=finding.recommendation,
                evidence=evidence,
                related_paths=paths,
            )
            key = (
                item.code.value,
                tuple((fact.kind.value, fact.value) for fact in evidence),
                paths,
            )
            normalized.setdefault(key, item)
        ordered = tuple(
            sorted(
                normalized.values(),
                key=lambda item: (
                    item.category.value,
                    item.code.value,
                    item.related_paths,
                    tuple((fact.kind.value, fact.value) for fact in item.evidence),
                ),
            )
        )
        if len(ordered) > self._limits.max_findings:
            return ordered[: self._limits.max_findings], True
        return ordered, truncated

    def _bounded_warnings(
        self,
        warnings: list[QualityWarning],
    ) -> tuple[QualityWarning, ...]:
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
        if len(ordered) <= self._limits.max_findings:
            return tuple(ordered)
        retained = ordered[: max(0, self._limits.max_findings - 1)]
        retained.append(self._warning(QualityWarningCode.QUALITY_WARNING_LIMIT_REACHED, None))
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
    def _summary(findings: tuple[QualityFinding, ...]) -> QualitySummary:
        severities = Counter(item.severity for item in findings)
        categories = Counter(item.category for item in findings)
        positive = sum(item.code in POSITIVE_FINDING_CODES for item in findings)
        return QualitySummary(
            total_finding_count=len(findings),
            high_count=severities[QualitySeverity.HIGH],
            medium_count=severities[QualitySeverity.MEDIUM],
            low_count=severities[QualitySeverity.LOW],
            info_count=severities[QualitySeverity.INFO],
            category_counts=tuple(
                QualityCategoryCount(category=category, count=count)
                for category, count in sorted(
                    categories.items(),
                    key=lambda item: item[0].value,
                )
            ),
            positive_signal_count=positive,
            improvement_finding_count=len(findings) - positive,
        )

    def _check_deadline(self, deadline: float) -> None:
        if self._clock() >= deadline:
            raise QualityAnalysisTimeout

    @staticmethod
    def _has_heading(headings: set[str], markers: frozenset[str]) -> bool:
        return any(
            heading == marker or heading.startswith(f"{marker} ") or heading.endswith(f" {marker}")
            for heading in headings
            for marker in markers
        )

    @staticmethod
    def _ci_signal_text(text: str) -> str:
        """Return only command-shaped CI lines for transient signal matching."""
        selected: list[str] = []
        block_indent: int | None = None
        for line in text.splitlines():
            stripped = line.strip()
            indent = len(line) - len(line.lstrip())
            if block_indent is not None:
                if stripped and indent > block_indent:
                    if not line.lstrip().startswith("#"):
                        selected.append(line)
                    continue
                block_indent = None
            if not stripped or line.lstrip().startswith("#"):
                continue
            if CI_COMMAND_LINE_PATTERN.match(line) is not None:
                selected.append(line)
                if line.rstrip().endswith(("|", ">")):
                    block_indent = indent
            elif CI_LIST_COMMAND_PATTERN.match(line) is not None:
                selected.append(line)
        return "\n".join(selected)

    @staticmethod
    def _empty_readme() -> ReadmeSignals:
        return ReadmeSignals(
            relative_path=None,
            readable=False,
            byte_count=0,
            nonempty_line_count=0,
            heading_count=0,
            code_fence_count=0,
            link_count=0,
            has_installation=False,
            has_usage=False,
            has_testing=False,
        )

    @staticmethod
    def _warning(
        code: QualityWarningCode,
        relative_path: str | None,
    ) -> QualityWarning:
        return QualityWarning(
            code=code,
            relative_path=(
                validate_quality_path(relative_path) if relative_path is not None else None
            ),
            message=QUALITY_WARNING_MESSAGES[code],
        )
