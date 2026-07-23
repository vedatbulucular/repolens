"""Central policies for supported source files and safe identifiers."""

import unicodedata
from pathlib import PurePosixPath

from repolens_api.inventory.policy import path_sort_key

SUPPORTED_SOURCE_LANGUAGES: dict[str, str] = {
    ".py": "Python",
    ".pyi": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".mts": "TypeScript",
    ".cts": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
}

MAX_SYMBOL_NAME_LENGTH = 255
MAX_QUALIFIED_NAME_LENGTH = 1_024
MAX_MODULE_NAME_LENGTH = 512


def supported_language(relative_path: str) -> str | None:
    """Return the supported parser language for one path."""
    return SUPPORTED_SOURCE_LANGUAGES.get(PurePosixPath(relative_path).suffix.casefold())


def is_safe_name(value: str, *, maximum: int = MAX_SYMBOL_NAME_LENGTH) -> bool:
    """Accept bounded printable names without control characters."""
    return (
        bool(value)
        and len(value) <= maximum
        and all(not unicodedata.category(character).startswith("C") for character in value)
    )


def qualified_name(scope: tuple[str, ...], name: str) -> str | None:
    """Build a bounded dotted qualified name."""
    value = ".".join((*scope, name))
    return value if is_safe_name(value, maximum=MAX_QUALIFIED_NAME_LENGTH) else None


def source_symbol_sort_key(
    relative_path: str,
    start_line: int,
    qualified: str,
    kind: str,
) -> tuple[object, ...]:
    """Return the deterministic cross-parser symbol ordering key."""
    return (*path_sort_key(relative_path), start_line, qualified.casefold(), qualified, kind)


def source_import_sort_key(
    relative_path: str,
    start_line: int,
    module: str,
    kind: str,
) -> tuple[object, ...]:
    """Return the deterministic cross-parser import ordering key."""
    return (*path_sort_key(relative_path), start_line, module.casefold(), module, kind)
