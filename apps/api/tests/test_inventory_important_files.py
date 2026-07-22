"""Tests for important-file grouping and category precedence."""

from pathlib import PurePosixPath

import pytest

from repolens_api.inventory.contracts import (
    ContentStatus,
    FileCategory,
    FileInventoryEntry,
)
from repolens_api.inventory.important_files import detect_important_files
from repolens_api.inventory.policy import categorize_file


def _entry(
    relative_path: str,
    *,
    language: str | None = None,
    is_binary: bool | None = False,
    status: ContentStatus = ContentStatus.AVAILABLE,
) -> FileInventoryEntry:
    path = PurePosixPath(relative_path)
    return FileInventoryEntry(
        relative_path=relative_path,
        name=path.name,
        extension=path.suffix.casefold(),
        size_bytes=1,
        language=language,
        category=FileCategory.OTHER,
        is_binary=is_binary,
        content_status=status,
    )


def _groups_by_kind(
    files: tuple[FileInventoryEntry, ...],
    directories: tuple[str, ...] = (),
) -> dict[str, tuple[str, ...]]:
    return {group.kind: group.paths for group in detect_important_files(files, directories)}


def test_documentation_names_are_case_insensitive_and_allow_variants() -> None:
    groups = _groups_by_kind(
        (
            _entry("README.MD"),
            _entry("docs/readme.txt"),
            _entry("License-Apache"),
        )
    )

    assert groups["readme"] == ("docs/readme.txt", "README.MD")
    assert groups["license"] == ("License-Apache",)


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("CONTRIBUTING.md", "contributing"),
        ("Changelog.txt", "changelog"),
        ("SECURITY", "security"),
        ("CODE_OF_CONDUCT.rst", "code_of_conduct"),
    ],
)
def test_other_documentation_families(name: str, kind: str) -> None:
    assert _groups_by_kind((_entry(name),))[kind] == (name,)


def test_multiple_files_keep_true_count_and_deterministic_paths() -> None:
    files = (_entry("z/README.md"), _entry("A/readme.md"), _entry("README.txt"))

    groups = detect_important_files(files, ())
    readme = next(group for group in groups if group.kind == "readme")

    assert readme.count == 3
    assert readme.paths == ("A/readme.md", "README.txt", "z/README.md")
    assert readme.truncated is False


def test_important_paths_are_truncated_but_count_is_preserved() -> None:
    files = tuple(_entry(f"test_{index:03}.py") for index in range(101))

    test_files = next(
        group for group in detect_important_files(files, ()) if group.kind == "test_file"
    )

    assert test_files.count == 101
    assert len(test_files.paths) == 100
    assert test_files.truncated is True


def test_github_workflow_is_detected_case_insensitively() -> None:
    groups = _groups_by_kind((_entry(".GitHub/Workflows/CI.YML"),))

    assert groups["github_actions_workflow"] == (".GitHub/Workflows/CI.YML",)


def test_test_directories_and_files_are_detected() -> None:
    groups = _groups_by_kind(
        (_entry("src/widget.spec.ts"), _entry("tests/helper.py")),
        ("src", "spec", "tests"),
    )

    assert groups["test_directory"] == ("spec", "tests")
    assert groups["test_file"] == ("src/widget.spec.ts", "tests/helper.py")


def test_environment_example_is_presence_only_sensitive_metadata() -> None:
    entry = _entry(
        ".env.example",
        is_binary=None,
        status=ContentStatus.SENSITIVE,
    )

    groups = _groups_by_kind((entry,))

    assert groups["environment_example"] == (".env.example",)


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("Dockerfile.dev", "dockerfile"),
        ("compose.yaml", "docker_compose"),
        ("docker-compose.yml", "docker_compose"),
        ("package.json", "package_manifest"),
        ("package-lock.json", "package_lock"),
        ("pnpm-lock.yaml", "pnpm_lock"),
        ("yarn.lock", "yarn_lock"),
        ("pyproject.toml", "python_project"),
        ("requirements.txt", "python_requirements"),
        ("uv.lock", "uv_lock"),
        ("pom.xml", "maven_project"),
        ("build.gradle", "gradle_build"),
        ("build.gradle.kts", "gradle_build"),
        ("Project.csproj", "dotnet_project"),
        ("Solution.sln", "dotnet_solution"),
        ("Cargo.toml", "cargo_manifest"),
        ("go.mod", "go_module"),
        ("Makefile", "makefile"),
        ("alembic.ini", "alembic"),
    ],
)
def test_build_and_ecosystem_files_are_detected(name: str, kind: str) -> None:
    groups = _groups_by_kind((_entry(name),))

    assert groups[kind] == (name,)


def test_important_group_order_is_deterministic() -> None:
    files = (_entry("package.json"), _entry("README.md"), _entry("Dockerfile"))

    groups = detect_important_files(files, ())

    assert tuple(group.kind for group in groups) == tuple(sorted(group.kind for group in groups))


@pytest.mark.parametrize(
    ("path", "language", "expected"),
    [
        ("tests/test_app.py", "Python", FileCategory.TEST),
        ("README.md", "Markdown", FileCategory.DOCUMENTATION),
        ("package.json", "JSON", FileCategory.DEPENDENCY_MANIFEST),
        ("pnpm-lock.yaml", "YAML", FileCategory.LOCKFILE),
        ("Dockerfile", None, FileCategory.BUILD),
        (".github/workflows/ci.yml", "YAML", FileCategory.CI),
        ("config.yaml", "YAML", FileCategory.CONFIGURATION),
        ("src/app.py", "Python", FileCategory.SOURCE),
        ("logo.png", None, FileCategory.ASSET),
        ("records.csv", None, FileCategory.DATA),
        ("NOTICE", None, FileCategory.OTHER),
    ],
)
def test_category_precedence(path: str, language: str | None, expected: FileCategory) -> None:
    assert categorize_file(path, language=language, is_binary=False) is expected
