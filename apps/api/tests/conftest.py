"""Shared isolated database and API fixtures."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from repolens_api.analysis_results import AnalysisOutput
from repolens_api.api import get_analysis_dispatcher
from repolens_api.code_structure.contracts import (
    CodeStructureResult,
    CodeStructureSummary,
    ImportFinding,
    LanguageFileCount,
    SourceFileStructure,
    SourceImportKind,
    SourceParseStatus,
    SourceStructureWarning,
    SourceStructureWarningCode,
    SourceSymbol,
    SourceSymbolKind,
)
from repolens_api.database import get_session
from repolens_api.inventory.contracts import (
    DirectoryFileCount,
    EntryPointFinding,
    FileCategory,
    FindingConfidence,
    ImportantFileGroup,
    InventoryLimits,
    InventoryResult,
    InventoryWarning,
    InventoryWarningCode,
    LanguageStatistic,
    RepositorySummary,
    TechnologyEvidence,
    TechnologyFinding,
)
from repolens_api.main import app
from repolens_api.models import Base


async def _create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


@pytest.fixture
def inventory_limits() -> InventoryLimits:
    """Return small but realistic limits for local inventory fixtures."""
    return InventoryLimits(
        timeout_seconds=5,
        max_entries=100,
        max_directories=50,
        max_path_length=200,
        max_manifest_bytes=1_024,
        max_text_read_bytes=512,
        binary_sample_bytes=64,
        max_warnings=20,
        max_json_nesting_depth=8,
        max_manifest_nodes=100,
        max_technology_findings=20,
        max_technology_evidence_per_finding=5,
        max_entry_points=20,
    )


@pytest.fixture
def inventory_result() -> InventoryResult:
    """Return a complete deterministic result without repository source content."""
    return InventoryResult(
        schema_version=1,
        repository_summary=RepositorySummary(
            regular_file_count=3,
            analyzed_directory_count=1,
            total_file_bytes=120,
            max_directory_depth=1,
            top_level_directories=("src",),
            directories_by_file_count=(DirectoryFileCount(relative_path="src", file_count=2),),
            ignored_directory_count=1,
            binary_file_count=0,
            unreadable_file_count=0,
            skipped_content_file_count=0,
            sensitive_file_count=0,
        ),
        languages=(
            LanguageStatistic(
                name="Python",
                file_count=2,
                total_bytes=100,
                percentage=100.0,
            ),
        ),
        important_files=(
            ImportantFileGroup(
                kind="readme",
                count=1,
                paths=("README.md",),
                truncated=False,
            ),
        ),
        technologies=(
            TechnologyFinding(
                name="FastAPI",
                category="framework",
                confidence=FindingConfidence.HIGH,
                evidence=(
                    TechnologyEvidence(
                        evidence_type="python_dependency",
                        relative_path="pyproject.toml",
                    ),
                ),
                evidence_truncated=False,
            ),
        ),
        entry_points=(
            EntryPointFinding(
                kind="python_module",
                relative_path="src/main.py",
                confidence=FindingConfidence.MEDIUM,
                evidence_type="filename_convention",
            ),
        ),
        warnings=(
            InventoryWarning(
                code=InventoryWarningCode.FILE_UNREADABLE,
                relative_path="docs/notes.txt",
                message="The file content could not be read safely.",
            ),
        ),
    )


@pytest.fixture
def code_structure_result() -> CodeStructureResult:
    """Return deterministic source structure without source bodies or literals."""
    return CodeStructureResult(
        summary=CodeStructureSummary(
            supported_source_file_count=1,
            parsed_file_count=1,
            skipped_file_count=0,
            parse_error_file_count=0,
            total_symbol_count=1,
            total_function_count=1,
            total_class_count=0,
            total_method_count=0,
            total_import_count=1,
            language_file_counts=(LanguageFileCount(language="Python", file_count=1),),
        ),
        files=(
            SourceFileStructure(
                relative_path="src/main.py",
                language="Python",
                category=FileCategory.SOURCE,
                line_count=4,
                symbol_count=1,
                import_count=1,
                class_count=0,
                function_count=1,
                method_count=0,
                parse_status=SourceParseStatus.PARSED,
                has_syntax_errors=False,
            ),
        ),
        symbols=(
            SourceSymbol(
                relative_path="src/main.py",
                language="Python",
                kind=SourceSymbolKind.FUNCTION,
                name="create_app",
                qualified_name="create_app",
                start_line=3,
                end_line=4,
                parent_name=None,
                parameter_count=0,
                is_exported=False,
                is_public=True,
            ),
        ),
        imports=(
            ImportFinding(
                relative_path="src/main.py",
                language="Python",
                module="fastapi",
                imported_names=("FastAPI",),
                import_kind=SourceImportKind.PYTHON_FROM_IMPORT,
                is_relative=False,
                start_line=1,
            ),
        ),
        warnings=(
            SourceStructureWarning(
                code=SourceStructureWarningCode.SOURCE_SYNTAX_ERROR,
                relative_path="src/legacy.py",
                message="The source file contains syntax errors.",
            ),
        ),
    )


@pytest.fixture
def analysis_output(
    inventory_result: InventoryResult,
    code_structure_result: CodeStructureResult,
) -> AnalysisOutput:
    """Return the current version 2 persisted worker output."""
    return AnalysisOutput(
        schema_version=2,
        inventory=inventory_result,
        code_structure=code_structure_result,
    )


@pytest.fixture
def test_sessions(tmp_path: Path) -> Iterator[async_sessionmaker[AsyncSession]]:
    database_path = tmp_path / "repolens-test.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    asyncio.run(_create_schema(engine))
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    yield sessions

    asyncio.run(engine.dispose())


@pytest.fixture
def dispatched_analysis_ids() -> list[UUID]:
    return []


@pytest.fixture
def api_client(
    test_sessions: async_sessionmaker[AsyncSession],
    dispatched_analysis_ids: list[UUID],
) -> Iterator[TestClient]:
    async def override_session() -> AsyncIterator[AsyncSession]:
        async with test_sessions() as session:
            yield session

    def record_dispatch(analysis_id: UUID) -> None:
        dispatched_analysis_ids.append(analysis_id)

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_analysis_dispatcher] = lambda: record_dispatch

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
