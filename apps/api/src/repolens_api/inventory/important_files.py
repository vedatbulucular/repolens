"""Case-insensitive important-file and test-signal detection."""

from collections import defaultdict
from pathlib import PurePosixPath

from repolens_api.inventory.contracts import FileInventoryEntry, ImportantFileGroup
from repolens_api.inventory.policy import (
    documentation_kind,
    is_ci_path,
    is_dockerfile,
    is_test_file,
    path_sort_key,
)

MAX_PATHS_PER_IMPORTANT_KIND = 100

EXACT_IMPORTANT_NAMES: dict[str, str] = {
    ".env.example": "environment_example",
    "alembic.ini": "alembic",
    "build.gradle": "gradle_build",
    "build.gradle.kts": "gradle_build",
    "cargo.toml": "cargo_manifest",
    "compose.yaml": "docker_compose",
    "compose.yml": "docker_compose",
    "docker-compose.yaml": "docker_compose",
    "docker-compose.yml": "docker_compose",
    "go.mod": "go_module",
    "makefile": "makefile",
    "package-lock.json": "package_lock",
    "package.json": "package_manifest",
    "pnpm-lock.yaml": "pnpm_lock",
    "pom.xml": "maven_project",
    "pyproject.toml": "python_project",
    "requirements.txt": "python_requirements",
    "uv.lock": "uv_lock",
    "yarn.lock": "yarn_lock",
}


def detect_important_files(
    files: tuple[FileInventoryEntry, ...],
    directories: tuple[str, ...],
) -> tuple[ImportantFileGroup, ...]:
    """Group bounded, sorted relative-path evidence by stable kind."""
    matches: defaultdict[str, set[str]] = defaultdict(set)
    for directory in directories:
        if PurePosixPath(directory).name.casefold() in {
            "test",
            "tests",
            "__tests__",
            "spec",
            "specs",
        }:
            matches["test_directory"].add(directory)

    for entry in files:
        path = PurePosixPath(entry.relative_path)
        name = path.name.casefold()
        documentation = documentation_kind(path.name)
        if documentation is not None:
            matches[documentation].add(entry.relative_path)
        exact_kind = EXACT_IMPORTANT_NAMES.get(name)
        if exact_kind is not None:
            matches[exact_kind].add(entry.relative_path)
        if is_dockerfile(path.name):
            matches["dockerfile"].add(entry.relative_path)
        if path.suffix.casefold() == ".csproj":
            matches["dotnet_project"].add(entry.relative_path)
        if path.suffix.casefold() == ".sln":
            matches["dotnet_solution"].add(entry.relative_path)
        if is_ci_path(entry.relative_path):
            matches["github_actions_workflow"].add(entry.relative_path)
        if is_test_file(entry.relative_path):
            matches["test_file"].add(entry.relative_path)

    groups: list[ImportantFileGroup] = []
    for kind in sorted(matches):
        ordered = tuple(sorted(matches[kind], key=path_sort_key))
        groups.append(
            ImportantFileGroup(
                kind=kind,
                count=len(ordered),
                paths=ordered[:MAX_PATHS_PER_IMPORTANT_KIND],
                truncated=len(ordered) > MAX_PATHS_PER_IMPORTANT_KIND,
            )
        )
    return tuple(groups)
