"""Tests for deterministic, bounded repository-quality findings."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from repolens_api.code_structure.contracts import (
    CodeStructureResult,
    CodeStructureSummary,
    LanguageFileCount,
    SourceFileStructure,
    SourceParseStatus,
    SourceStructureWarning,
    SourceStructureWarningCode,
)
from repolens_api.code_structure.service import CodeStructureService
from repolens_api.inventory.content import SafeContentReader, TextReadResult
from repolens_api.inventory.contracts import (
    ContentStatus,
    FileCategory,
    FileInventoryEntry,
    InventoryLimits,
    InventoryResult,
)
from repolens_api.inventory.service import InventoryService
from repolens_api.quality_findings.contracts import (
    QualityFindingCode,
    QualityFindingsResult,
    QualityLimits,
    QualityWarningCode,
)
from repolens_api.quality_findings.errors import (
    QualityAnalysisLimitExceeded,
    QualityAnalysisTimeout,
    UnsafeQualityPath,
)
from repolens_api.quality_findings.policy import FINDING_TEXTS
from repolens_api.quality_findings.service import QualityFindingsService
from repolens_api.settings import Settings


def _quality_limits(**overrides: int) -> QualityLimits:
    values = {
        "timeout_seconds": 5,
        "max_findings": 100,
        "max_related_paths": 20,
        "max_evidence_items": 20,
        "max_document_read_bytes": 4_096,
    }
    values.update(overrides)
    return QualityLimits(**values)


def _analyze(
    repository_root: Path,
    inventory_limits: InventoryLimits,
    *,
    limits: QualityLimits | None = None,
    reader: SafeContentReader | None = None,
    clock: Callable[[], float] | None = None,
) -> tuple[set[QualityFindingCode], QualityFindingsResult]:
    content_reader = reader or SafeContentReader(inventory_limits)
    analysis = InventoryService(
        inventory_limits,
        content_reader=content_reader,
    ).analyze_with_files(repository_root)
    structure = CodeStructureService(
        Settings().source_structure_limits(),
        content_reader=content_reader,
    ).analyze(repository_root, analysis.files)
    service = (
        QualityFindingsService(
            limits or _quality_limits(),
            content_reader=content_reader,
            clock=clock,
        )
        if clock is not None
        else QualityFindingsService(
            limits or _quality_limits(),
            content_reader=content_reader,
        )
    )
    result = service.analyze(
        repository_root,
        inventory=analysis.result,
        files=analysis.files,
        directories=analysis.directories,
        manifests=analysis.manifest_facts,
        structure=structure,
    )
    return {finding.code for finding in result.findings}, result


def _complete_readme(*, comments_only: bool = False) -> str:
    headings = (
        "<!--\n# Installation\n# Usage\n# Testing\n-->\n"
        "The words installation, usage, and testing are not headings.\n"
        if comments_only
        else "# Installation\nsetup details\n# Usage\nusage details\n# Testing\ntest details\n"
    )
    return "# Project\n" + headings + "\n".join(f"Project detail {index}" for index in range(40))


def test_missing_and_small_readme_findings(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    codes, _ = _analyze(tmp_path, inventory_limits)
    assert QualityFindingCode.README_MISSING in codes

    (tmp_path / "README.md").write_text("# Project\nShort.", encoding="utf-8")
    codes, _ = _analyze(tmp_path, inventory_limits)
    assert QualityFindingCode.README_TOO_SMALL in codes
    assert QualityFindingCode.README_MISSING not in codes
    assert QualityFindingCode.DOCUMENTATION_PRESENT not in codes


def test_missing_tests_ci_lockfile_and_entry_point_are_reported(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")

    codes, _ = _analyze(tmp_path, inventory_limits)

    assert {
        QualityFindingCode.TESTS_MISSING,
        QualityFindingCode.CI_MISSING,
        QualityFindingCode.LOCKFILE_MISSING,
        QualityFindingCode.ENTRY_POINT_MISSING,
    } <= codes


def test_complete_readme_and_docs_produce_positive_documentation(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "README.md").write_text(
        _complete_readme(),
        encoding="utf-8-sig",
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "architecture.md").write_text("# Architecture", encoding="utf-8")

    codes, result = _analyze(tmp_path, inventory_limits)

    assert QualityFindingCode.DOCUMENTATION_PRESENT in codes
    assert QualityFindingCode.README_INSTALLATION_MISSING not in codes
    assert QualityFindingCode.README_USAGE_MISSING not in codes
    assert QualityFindingCode.README_TESTING_MISSING not in codes
    assert result.summary.positive_signal_count > 0


def test_readme_comments_do_not_create_section_signals(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "README.md").write_text(
        _complete_readme(comments_only=True),
        encoding="utf-8",
    )

    codes, _ = _analyze(tmp_path, inventory_limits)

    assert QualityFindingCode.README_INSTALLATION_MISSING in codes
    assert QualityFindingCode.README_USAGE_MISSING in codes
    assert QualityFindingCode.README_TESTING_MISSING in codes


@pytest.mark.parametrize(
    ("content", "expected_warning"),
    [
        (b"\xff\xfeP\x00r\x00i\x00v\x00a\x00t\x00e\x00", "quality_document_unsupported_encoding"),
        (b"# Project\x00PRIVATE README PARAGRAPH", "quality_document_unsupported_encoding"),
    ],
)
def test_unsupported_documents_emit_safe_warning_without_content(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
    content: bytes,
    expected_warning: str,
) -> None:
    (tmp_path / "README.md").write_bytes(content)

    _, result = _analyze(tmp_path, inventory_limits)

    assert [warning.code.value for warning in result.warnings] == [expected_warning]
    assert "PRIVATE" not in repr(result)


def test_oversized_and_unreadable_documents_emit_fixed_warnings(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("x" * 200, encoding="utf-8")
    _, oversized = _analyze(
        tmp_path,
        inventory_limits,
        limits=_quality_limits(max_document_read_bytes=100),
    )
    assert oversized.warnings[0].code is QualityWarningCode.QUALITY_DOCUMENT_TOO_LARGE

    class UnreadableReader(SafeContentReader):
        def read_text(self, *_args: object, **_kwargs: object) -> TextReadResult:
            return TextReadResult(None, ContentStatus.UNREADABLE)

    reader = UnreadableReader(inventory_limits)
    _, unreadable = _analyze(tmp_path, inventory_limits, reader=reader)
    assert unreadable.warnings[0].code is QualityWarningCode.QUALITY_DOCUMENT_UNREADABLE
    assert unreadable.warnings[0].message == (
        "A quality-analysis document could not be read safely."
    )


def test_tests_manifest_and_ci_are_detected_without_executing_commands(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def app():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text(
        "def test_app():\n    assert True\n",
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        '{"devDependencies":{"vitest":"private","jest":"private"},'
        '"scripts":{"test":"PRIVATE COMMAND"}}',
        encoding="utf-8",
    )
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(
        "# pytest private-command\nsteps:\n  - run: |\n      pnpm test\n"
        "      pnpm lint\n      pnpm build\n",
        encoding="utf-8",
    )

    codes, result = _analyze(tmp_path, inventory_limits)

    assert {
        QualityFindingCode.TESTS_PRESENT,
        QualityFindingCode.TEST_CONFIGURATION_PRESENT,
        QualityFindingCode.MULTIPLE_TEST_FRAMEWORKS_PRESENT,
        QualityFindingCode.TEST_CI_INTEGRATION_PRESENT,
        QualityFindingCode.CI_PRESENT,
    } <= codes
    assert QualityFindingCode.CI_QUALITY_CHECKS_MISSING not in codes
    assert "PRIVATE COMMAND" not in repr(result)
    assert "private-command" not in repr(result)


def test_ci_comments_do_not_create_quality_check_signals(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(
        "# run pytest, ruff, and build\nname: test lint build metadata only\n",
        encoding="utf-8",
    )

    codes, _ = _analyze(tmp_path, inventory_limits)

    assert QualityFindingCode.CI_PRESENT in codes
    assert QualityFindingCode.CI_QUALITY_CHECKS_MISSING in codes


def test_sparse_test_threshold_is_deterministic(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "src").mkdir()
    for index in range(10):
        (tmp_path / "src" / f"module_{index}.py").write_text(
            f"value_{index} = {index}\n",
            encoding="utf-8",
        )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_one.py").write_text("assert True\n", encoding="utf-8")

    codes, _ = _analyze(tmp_path, inventory_limits)
    assert QualityFindingCode.TESTS_SPARSE not in codes

    (tmp_path / "src" / "module_10.py").write_text("value = 10\n", encoding="utf-8")
    codes, _ = _analyze(tmp_path, inventory_limits)
    assert QualityFindingCode.TESTS_SPARSE in codes


def test_governance_automation_and_onboarding_signals(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    for name in ("LICENSE", "CONTRIBUTING.md", "SECURITY.md", ".env.example"):
        (tmp_path / name).write_text("safe", encoding="utf-8")
    (tmp_path / "CODEOWNERS").write_text("* @team", encoding="utf-8")
    (tmp_path / "compose.yaml").write_text("services: {}", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: 9", encoding="utf-8")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "dependabot.yml").write_text("version: 2", encoding="utf-8")

    codes, _ = _analyze(tmp_path, inventory_limits)

    assert {
        QualityFindingCode.LICENSE_PRESENT,
        QualityFindingCode.CONTRIBUTING_PRESENT,
        QualityFindingCode.SECURITY_POLICY_PRESENT,
        QualityFindingCode.COMMUNITY_FILES_PRESENT,
        QualityFindingCode.DEPENDENCY_UPDATE_AUTOMATION_PRESENT,
        QualityFindingCode.CONTAINER_SETUP_PRESENT,
        QualityFindingCode.ENVIRONMENT_EXAMPLE_PRESENT,
        QualityFindingCode.LOCKFILE_PRESENT,
        QualityFindingCode.DEVELOPMENT_SETUP_PRESENT,
    } <= codes
    assert QualityFindingCode.LICENSE_MISSING not in codes
    assert QualityFindingCode.LOCKFILE_MISSING not in codes


def test_maintainability_rules_use_only_bounded_structure_facts(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
    inventory_result: InventoryResult,
) -> None:
    relative_paths = ("src/dominant.py", "src/second.py", "src/third.py")
    files = tuple(
        FileInventoryEntry(
            relative_path=path,
            name=Path(path).name,
            extension=".py",
            size_bytes=140_000 if index == 0 else 10,
            language="Python",
            category=FileCategory.SOURCE,
            is_binary=False,
            content_status=ContentStatus.AVAILABLE,
        )
        for index, path in enumerate(relative_paths)
    )
    structure_files = tuple(
        SourceFileStructure(
            relative_path=path,
            language="Python",
            category=FileCategory.SOURCE,
            line_count=200,
            symbol_count=(120, 10, 10)[index],
            import_count=60 if index == 0 else 0,
            class_count=1,
            function_count=0,
            method_count=60 if index == 0 else 0,
            parse_status=SourceParseStatus.PARTIAL if index == 2 else SourceParseStatus.PARSED,
            has_syntax_errors=index == 2,
        )
        for index, path in enumerate(relative_paths)
    )
    warning = SourceStructureWarning(
        code=SourceStructureWarningCode.SOURCE_SYNTAX_ERROR,
        relative_path="src/third.py",
        message="The source file contains syntax errors.",
    )
    structure = CodeStructureResult(
        summary=CodeStructureSummary(
            supported_source_file_count=3,
            parsed_file_count=2,
            skipped_file_count=0,
            parse_error_file_count=1,
            total_symbol_count=140,
            total_function_count=0,
            total_class_count=3,
            total_method_count=60,
            total_import_count=60,
            language_file_counts=(LanguageFileCount(language="Python", file_count=3),),
        ),
        files=structure_files,
        symbols=(),
        imports=(),
        warnings=(warning,) * 10,
    )
    service = QualityFindingsService(
        _quality_limits(),
        content_reader=SafeContentReader(inventory_limits),
    )
    result = service.analyze(
        tmp_path,
        inventory=replace(inventory_result, important_files=(), entry_points=()),
        files=files,
        directories=("src",),
        manifests=(),
        structure=structure,
    )
    codes = {finding.code for finding in result.findings}

    assert {
        QualityFindingCode.OVERSIZED_SOURCE_FILE,
        QualityFindingCode.SYMBOL_DENSE_FILE,
        QualityFindingCode.IMPORT_DENSE_FILE,
        QualityFindingCode.METHOD_DENSE_FILE,
        QualityFindingCode.SOURCE_CONCENTRATION_HIGH,
        QualityFindingCode.SOURCE_PARSE_ERRORS_PRESENT,
        QualityFindingCode.STRUCTURE_WARNINGS_HIGH,
    } <= codes


def test_limits_truncate_deterministically_and_emit_warning(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "README.md").write_text(_complete_readme(), encoding="utf-8")
    (tmp_path / "tests").mkdir()
    for index in range(4):
        (tmp_path / "tests" / f"test_{index}.py").write_text(
            "assert True\n",
            encoding="utf-8",
        )

    _, first = _analyze(
        tmp_path,
        inventory_limits,
        limits=_quality_limits(
            max_findings=4,
            max_related_paths=1,
            max_evidence_items=1,
        ),
    )
    _, second = _analyze(
        tmp_path,
        inventory_limits,
        limits=_quality_limits(
            max_findings=4,
            max_related_paths=1,
            max_evidence_items=1,
        ),
    )

    assert first == second
    assert len(first.findings) == 4
    assert all(len(finding.related_paths) <= 1 for finding in first.findings)
    assert all(len(finding.evidence) <= 1 for finding in first.findings)
    assert any(
        warning.code is QualityWarningCode.QUALITY_FINDINGS_TRUNCATED for warning in first.warnings
    )
    keys = {(finding.code, finding.related_paths, finding.evidence) for finding in first.findings}
    assert len(keys) == len(first.findings)


def test_warning_limit_is_bounded_with_fixed_terminal_warning(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "README.md").write_text(_complete_readme(), encoding="utf-8")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    for name in ("ci.yml", "security.yml"):
        (tmp_path / ".github" / "workflows" / name).write_text(
            "name: safe\n",
            encoding="utf-8",
        )

    class UnreadableReader(SafeContentReader):
        def read_text(self, *_args: object, **_kwargs: object) -> TextReadResult:
            return TextReadResult(None, ContentStatus.UNREADABLE)

    _, result = _analyze(
        tmp_path,
        inventory_limits,
        limits=_quality_limits(max_findings=2),
        reader=UnreadableReader(inventory_limits),
    )

    assert len(result.warnings) == 2
    assert any(
        warning.code is QualityWarningCode.QUALITY_WARNING_LIMIT_REACHED
        for warning in result.warnings
    )


def test_total_deadline_and_unsafe_paths_fail_with_safe_codes(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
    inventory_result: InventoryResult,
    code_structure_result: CodeStructureResult,
) -> None:
    ticks = iter((0.0, 2.0))
    timeout_service = QualityFindingsService(
        _quality_limits(timeout_seconds=1),
        content_reader=SafeContentReader(inventory_limits),
        clock=lambda: next(ticks),
    )
    with pytest.raises(QualityAnalysisTimeout):
        timeout_service.analyze(
            tmp_path,
            inventory=inventory_result,
            files=(),
            directories=(),
            manifests=(),
            structure=code_structure_result,
        )

    unsafe = FileInventoryEntry(
        relative_path="C:/private/README.md",
        name="README.md",
        extension=".md",
        size_bytes=1,
        language=None,
        category=FileCategory.DOCUMENTATION,
        is_binary=False,
        content_status=ContentStatus.AVAILABLE,
    )
    unsafe_service = QualityFindingsService(
        _quality_limits(),
        content_reader=SafeContentReader(inventory_limits),
    )
    with pytest.raises(UnsafeQualityPath) as raised:
        unsafe_service.analyze(
            tmp_path,
            inventory=inventory_result,
            files=(unsafe,),
            directories=(),
            manifests=(),
            structure=code_structure_result,
        )
    assert "C:" not in str(raised.value)


def test_nonpositive_service_limit_fails_safely(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
    inventory_result: InventoryResult,
    code_structure_result: CodeStructureResult,
) -> None:
    service = QualityFindingsService(
        _quality_limits(max_findings=0),
        content_reader=SafeContentReader(inventory_limits),
    )

    with pytest.raises(QualityAnalysisLimitExceeded):
        service.analyze(
            tmp_path,
            inventory=inventory_result,
            files=(),
            directories=(),
            manifests=(),
            structure=code_structure_result,
        )


def test_sensitive_document_content_is_never_read(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    secret = "PRIVATE_SECRET_VALUE"
    (tmp_path / "README.key").write_text(secret, encoding="utf-8")

    _, result = _analyze(tmp_path, inventory_limits)

    assert secret not in repr(result)
    assert result.warnings == ()


def test_symlink_document_is_rejected(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
    inventory_result: InventoryResult,
    code_structure_result: CodeStructureResult,
) -> None:
    outside = tmp_path.parent / "private-readme.md"
    outside.write_text("PRIVATE", encoding="utf-8")
    link = tmp_path / "README.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is not available")
    entry = FileInventoryEntry(
        relative_path="README.md",
        name="README.md",
        extension=".md",
        size_bytes=outside.stat().st_size,
        language=None,
        category=FileCategory.DOCUMENTATION,
        is_binary=False,
        content_status=ContentStatus.AVAILABLE,
    )
    service = QualityFindingsService(
        _quality_limits(),
        content_reader=SafeContentReader(inventory_limits),
    )

    with pytest.raises(UnsafeQualityPath):
        service.analyze(
            tmp_path,
            inventory=inventory_result,
            files=(entry,),
            directories=(),
            manifests=(),
            structure=code_structure_result,
        )


def test_every_finding_code_has_fixed_safe_metadata() -> None:
    assert set(FINDING_TEXTS) == set(QualityFindingCode)
    assert all(
        text.title and text.message and text.recommendation for text in FINDING_TEXTS.values()
    )
