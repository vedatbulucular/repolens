"""Central deterministic filename and directory policies."""

from pathlib import PurePosixPath

from repolens_api.inventory.contracts import FileCategory
from repolens_api.inventory.errors import UnsafeRepositoryPath

IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "vendor",
        "dist",
        "build",
        "coverage",
        ".next",
        "target",
        "bin",
        "obj",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
)

TEST_DIRECTORY_NAMES = frozenset({"test", "tests", "__tests__", "spec", "specs"})

SENSITIVE_EXACT_NAMES = frozenset(
    {
        ".env",
        ".netrc",
        ".npmrc",
        ".pypirc",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "id_xmss",
    }
)
SENSITIVE_SUFFIXES = frozenset({".jks", ".key", ".p12", ".pem", ".pfx"})

DEPENDENCY_MANIFEST_NAMES = frozenset(
    {
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "cargo.toml",
        "go.mod",
    }
)
LOCKFILE_NAMES = frozenset({"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock"})
BUILD_FILE_NAMES = frozenset(
    {
        "compose.yaml",
        "compose.yml",
        "docker-compose.yaml",
        "docker-compose.yml",
        "makefile",
    }
)
CONFIGURATION_EXTENSIONS = frozenset({".ini", ".json", ".toml", ".xml", ".yaml", ".yml"})
ASSET_EXTENSIONS = frozenset(
    {
        ".7z",
        ".avi",
        ".bmp",
        ".eot",
        ".gif",
        ".gz",
        ".ico",
        ".jpeg",
        ".jpg",
        ".mov",
        ".mp3",
        ".mp4",
        ".pdf",
        ".png",
        ".rar",
        ".tar",
        ".ttf",
        ".wav",
        ".webp",
        ".woff",
        ".woff2",
        ".zip",
    }
)
DATA_EXTENSIONS = frozenset({".csv", ".parquet", ".tsv"})

DOCUMENTATION_FAMILIES: tuple[tuple[str, str], ...] = (
    ("code_of_conduct", "code_of_conduct"),
    ("contributing", "contributing"),
    ("changelog", "changelog"),
    ("security", "security"),
    ("license", "license"),
    ("readme", "readme"),
)


def path_sort_key(path: str) -> tuple[str, str]:
    """Return the repository-wide deterministic path sort key."""
    return path.casefold(), path


def is_ignored_directory(name: str) -> bool:
    """Return whether a directory must be pruned without traversal."""
    return name.casefold() in IGNORED_DIRECTORY_NAMES


def is_sensitive_file(relative_path: str) -> bool:
    """Return whether file contents must never be opened."""
    name = PurePosixPath(relative_path).name.casefold()
    if name in SENSITIVE_EXACT_NAMES or name.startswith(".env."):
        return True
    if PurePosixPath(name).suffix in SENSITIVE_SUFFIXES:
        return True
    stem = PurePosixPath(name).stem
    normalized_stem = stem.replace("_", "-").replace(".", "-")
    return (
        "credential" in normalized_stem
        or "service-account" in normalized_stem
        or "serviceaccount" in normalized_stem
    )


def validate_relative_path(relative_path: PurePosixPath, max_length: int) -> str:
    """Validate and return one safe, UTF-8 POSIX relative path."""
    if relative_path.is_absolute() or not relative_path.parts:
        raise UnsafeRepositoryPath
    if any(part in {"", ".", ".."} or "\\" in part for part in relative_path.parts):
        raise UnsafeRepositoryPath
    normalized = relative_path.as_posix()
    try:
        normalized.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise UnsafeRepositoryPath from None
    if len(normalized) > max_length:
        raise UnsafeRepositoryPath
    return normalized


def documentation_kind(name: str) -> str | None:
    """Return the matching documentation family for one basename."""
    folded = name.casefold()
    for kind, base in DOCUMENTATION_FAMILIES:
        if folded == base or folded.startswith((f"{base}.", f"{base}-", f"{base}_")):
            return kind
    return None


def is_test_directory_path(relative_path: str) -> bool:
    """Return whether any directory component is a conservative test directory."""
    return any(
        part.casefold() in TEST_DIRECTORY_NAMES for part in PurePosixPath(relative_path).parts
    )


def is_test_file_name(name: str) -> bool:
    """Match common ecosystem-neutral test filename conventions."""
    folded = name.casefold()
    stem = PurePosixPath(folded).stem
    original_stem = PurePosixPath(name).stem
    prefixed_class_name = any(
        original_stem.startswith(prefix)
        and len(original_stem) > len(prefix)
        and original_stem[len(prefix)].isupper()
        for prefix in ("Spec", "Test")
    )
    return (
        stem in {"spec", "specs", "test", "tests"}
        or folded.startswith("test_")
        or stem.endswith(("_test", "_tests", "_spec", "_specs"))
        or original_stem.endswith(("Test", "Tests", "Spec", "Specs"))
        or prefixed_class_name
        or ".test." in folded
        or ".tests." in folded
        or ".spec." in folded
        or ".specs." in folded
    )


def is_test_file(relative_path: str) -> bool:
    """Return whether a file is inside a test directory or has a test name."""
    return is_test_directory_path(relative_path) or is_test_file_name(
        PurePosixPath(relative_path).name
    )


def is_ci_path(relative_path: str) -> bool:
    """Return whether a file is a GitHub Actions YAML workflow."""
    path = PurePosixPath(relative_path)
    folded_parts = tuple(part.casefold() for part in path.parts)
    return (
        len(folded_parts) >= 3
        and folded_parts[:2] == (".github", "workflows")
        and path.suffix.casefold() in {".yaml", ".yml"}
    )


def is_dockerfile(name: str) -> bool:
    """Return whether a basename is Dockerfile or a Dockerfile variant."""
    folded = name.casefold()
    return folded == "dockerfile" or folded.startswith("dockerfile.")


def categorize_file(
    relative_path: str,
    *,
    language: str | None,
    is_binary: bool | None,
) -> FileCategory:
    """Apply the documented single-category precedence."""
    path = PurePosixPath(relative_path)
    name = path.name.casefold()
    extension = path.suffix.casefold()

    if is_test_file(relative_path):
        return FileCategory.TEST
    if documentation_kind(path.name) is not None:
        return FileCategory.DOCUMENTATION
    if name in DEPENDENCY_MANIFEST_NAMES or extension in {".csproj", ".sln"}:
        return FileCategory.DEPENDENCY_MANIFEST
    if name in LOCKFILE_NAMES:
        return FileCategory.LOCKFILE
    if is_dockerfile(path.name) or name in BUILD_FILE_NAMES:
        return FileCategory.BUILD
    if is_ci_path(relative_path):
        return FileCategory.CI
    if is_sensitive_file(relative_path) or name == "alembic.ini":
        return FileCategory.CONFIGURATION
    if extension in CONFIGURATION_EXTENSIONS:
        return FileCategory.CONFIGURATION
    if language is not None:
        return FileCategory.SOURCE
    if is_binary is True or extension in ASSET_EXTENSIONS:
        return FileCategory.ASSET
    if extension in DATA_EXTENSIONS:
        return FileCategory.DATA
    return FileCategory.OTHER
