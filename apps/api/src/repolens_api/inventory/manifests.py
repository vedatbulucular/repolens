"""Safe, bounded extraction of allowlisted repository manifest facts."""

from __future__ import annotations

import json
import re
import tomllib
import xml.etree.ElementTree as element_tree
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import cast

from repolens_api.inventory.content import SafeContentReader
from repolens_api.inventory.contracts import (
    ContentStatus,
    FileInventoryEntry,
    InventoryLimits,
    InventoryWarning,
    InventoryWarningCode,
    ManifestFact,
    ManifestRelativePath,
)
from repolens_api.inventory.policy import is_ci_path, is_dockerfile, path_sort_key

PACKAGE_NAME_PATTERN = re.compile(
    r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$",
    re.IGNORECASE,
)
PYTHON_REQUIREMENT_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[[A-Za-z0-9._,-]+\])?"
    r"(?:\s*(?:===|==|!=|~=|>=|<=|>|<).*)?"
    r"(?:\s*;.*)?$",
)
SAFE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9@._:+/-]{1,200}$")
GRADLE_SPRING_BOOT_PATTERN = re.compile(
    r"\bid\s*(?:\(\s*[\"']org\.springframework\.boot[\"']\s*\)|"
    r"[\"']org\.springframework\.boot[\"'])"
)
GRADLE_DEPENDENCY_MANAGEMENT_PATTERN = re.compile(
    r"\bid\s*(?:\(\s*[\"']io\.spring\.dependency-management[\"']\s*\)|"
    r"[\"']io\.spring\.dependency-management[\"'])"
)
COMPOSE_NAMES = frozenset(
    {"compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"}
)
PACKAGE_DEPENDENCY_KEYS = (
    "dependencies",
    "devDependencies",
    "peerDependencies",
    "optionalDependencies",
)


@dataclass(frozen=True, slots=True)
class ManifestExtraction:
    """Deterministic facts and safe non-fatal warnings from manifests."""

    facts: tuple[ManifestFact, ...]
    warnings: tuple[InventoryWarning, ...]


class _LimitKind(Enum):
    NESTING = "nesting"
    NODES = "nodes"


class _ManifestLimitError(Exception):
    def __init__(self, kind: _LimitKind) -> None:
        self.kind = kind


def extract_manifest_facts(
    repository_root: Path,
    files: tuple[FileInventoryEntry, ...],
    content_reader: SafeContentReader,
    limits: InventoryLimits,
) -> ManifestExtraction:
    """Extract only explicitly allowlisted facts from inventoried regular files."""
    facts: list[ManifestFact] = []
    warnings: list[InventoryWarning] = []
    for entry in files:
        parser = _parser_for(entry.relative_path)
        if parser is not None:
            parser_presence = _parser_presence_fact(entry.relative_path)
            if parser_presence is not None:
                facts.append(parser_presence)
            text, read_warning = _read_manifest(
                repository_root,
                entry,
                content_reader,
                limits,
            )
            if read_warning is not None:
                warnings.append(read_warning)
                continue
            if text is None:
                continue
            try:
                fact, parse_warnings = parser(text, entry.relative_path, limits)
            except _ManifestLimitError as exc:
                warnings.append(_limit_warning(exc.kind, entry.relative_path))
                continue
            except _ManifestParseError as exc:
                warnings.append(
                    _warning(
                        (
                            InventoryWarningCode.UNSAFE_MANIFEST_VALUE
                            if exc.unsafe
                            else InventoryWarningCode.MANIFEST_PARSE_FAILED
                        ),
                        entry.relative_path,
                        (
                            "The manifest contains an unsafe value."
                            if exc.unsafe
                            else "The manifest could not be parsed safely."
                        ),
                    )
                )
                continue
            if fact is not None:
                facts.append(fact)
            warnings.extend(parse_warnings)
            continue

        presence = _presence_fact(entry.relative_path)
        if presence is not None:
            facts.append(presence)

    return ManifestExtraction(
        facts=tuple(
            sorted(
                facts,
                key=lambda fact: (fact.kind, *path_sort_key(fact.relative_path)),
            )
        ),
        warnings=tuple(
            sorted(
                warnings,
                key=lambda warning: (
                    warning.code.value,
                    *path_sort_key(warning.relative_path or ""),
                ),
            )
        ),
    )


type _ManifestParser = Callable[
    [str, str, InventoryLimits],
    tuple[ManifestFact | None, tuple[InventoryWarning, ...]],
]


def _parser_for(
    relative_path: str,
) -> _ManifestParser | None:
    name = PurePosixPath(relative_path).name.casefold()
    if name == "package.json":
        return _parse_package_json
    if name == "pyproject.toml":
        return _parse_pyproject
    if name == "cargo.toml":
        return _parse_cargo
    if name == "requirements.txt":
        return _parse_requirements
    if name == "pom.xml":
        return _parse_pom
    if PurePosixPath(relative_path).suffix.casefold() == ".csproj":
        return _parse_csproj
    if name in {"build.gradle", "build.gradle.kts"}:
        return _parse_gradle
    return None


def _read_manifest(
    repository_root: Path,
    entry: FileInventoryEntry,
    content_reader: SafeContentReader,
    limits: InventoryLimits,
) -> tuple[str | None, InventoryWarning | None]:
    result = content_reader.read_text(
        repository_root,
        entry.relative_path,
        expected_size=entry.size_bytes,
        max_bytes=limits.max_manifest_bytes,
    )
    if result.text is not None:
        return result.text, None
    if result.content_status is ContentStatus.TOO_LARGE:
        return None, _warning(
            InventoryWarningCode.MANIFEST_TOO_LARGE,
            entry.relative_path,
            "The manifest exceeds the allowed read size.",
        )
    if result.content_status is ContentStatus.UNSUPPORTED_ENCODING:
        return None, _warning(
            InventoryWarningCode.UNSUPPORTED_FILE_ENCODING,
            entry.relative_path,
            "The manifest uses an unsupported text encoding.",
        )
    if result.content_status is ContentStatus.BINARY:
        return None, _warning(
            InventoryWarningCode.UNSAFE_MANIFEST_VALUE,
            entry.relative_path,
            "The manifest contains an unsafe value.",
        )
    return None, _warning(
        InventoryWarningCode.MANIFEST_PARSE_FAILED,
        entry.relative_path,
        "The manifest could not be parsed safely.",
    )


def _parse_package_json(
    text: str,
    relative_path: str,
    limits: InventoryLimits,
) -> tuple[ManifestFact | None, tuple[InventoryWarning, ...]]:
    value = _load_json(text, relative_path, limits)
    root = _mapping(value)
    if root is None:
        return None, (
            _warning(
                InventoryWarningCode.MANIFEST_PARSE_FAILED,
                relative_path,
                "The manifest root must be an object.",
            ),
        )

    names: set[str] = set()
    warnings: list[InventoryWarning] = []
    for key in PACKAGE_DEPENDENCY_KEYS:
        dependencies = _mapping(root.get(key))
        if dependencies is None:
            continue
        for raw_name in dependencies:
            normalized = _normalize_package_name(raw_name)
            if normalized is None:
                warnings.append(_skipped_warning(relative_path))
            else:
                names.add(normalized)

    flags: set[str] = set()
    scripts = _mapping(root.get("scripts"))
    if scripts is not None:
        for script_name in ("start", "dev", "serve", "test"):
            if script_name in scripts:
                flags.add(f"has_{script_name}_script")

    relative_paths: list[ManifestRelativePath] = []
    raw_main = root.get("main")
    if raw_main is not None:
        safe_main = (
            _safe_relative_manifest_path(raw_main, limits.max_path_length)
            if isinstance(raw_main, str)
            else None
        )
        if safe_main is None:
            warnings.append(
                _warning(
                    InventoryWarningCode.UNSAFE_MANIFEST_VALUE,
                    relative_path,
                    "The manifest contains an unsafe value.",
                )
            )
        else:
            relative_paths.append(ManifestRelativePath("node_main", safe_main))

    return (
        _fact(
            "package_json",
            relative_path,
            names,
            flags,
            relative_paths,
        ),
        tuple(warnings),
    )


def _parse_pyproject(
    text: str,
    relative_path: str,
    limits: InventoryLimits,
) -> tuple[ManifestFact | None, tuple[InventoryWarning, ...]]:
    root = _load_toml(text, relative_path, limits)
    names: set[str] = set()
    warnings: list[InventoryWarning] = []

    project = _mapping(root.get("project"))
    if project is not None:
        _collect_requirement_list(project.get("dependencies"), names, warnings, relative_path)
        optional = _mapping(project.get("optional-dependencies"))
        if optional is not None:
            for requirements in optional.values():
                _collect_requirement_list(requirements, names, warnings, relative_path)

    tool = _mapping(root.get("tool"))
    poetry = _mapping(tool.get("poetry")) if tool is not None else None
    if poetry is not None:
        _collect_mapping_keys(
            poetry.get("dependencies"),
            names,
            warnings,
            relative_path,
            python=True,
        )
        groups = _mapping(poetry.get("group"))
        if groups is not None:
            for group in groups.values():
                group_mapping = _mapping(group)
                if group_mapping is not None:
                    _collect_mapping_keys(
                        group_mapping.get("dependencies"),
                        names,
                        warnings,
                        relative_path,
                        python=True,
                    )

    dependency_groups = _mapping(root.get("dependency-groups"))
    if dependency_groups is not None:
        for requirements in dependency_groups.values():
            _collect_requirement_list(requirements, names, warnings, relative_path)

    build_system = _mapping(root.get("build-system"))
    if build_system is not None:
        _collect_requirement_list(build_system.get("requires"), names, warnings, relative_path)

    return _fact("pyproject", relative_path, names), tuple(warnings)


def _parse_cargo(
    text: str,
    relative_path: str,
    limits: InventoryLimits,
) -> tuple[ManifestFact | None, tuple[InventoryWarning, ...]]:
    root = _load_toml(text, relative_path, limits)
    names: set[str] = set()
    warnings: list[InventoryWarning] = []
    for key in ("dependencies", "dev-dependencies", "build-dependencies"):
        _collect_mapping_keys(root.get(key), names, warnings, relative_path, python=False)

    flags: set[str] = set()
    if _mapping(root.get("package")) is not None:
        flags.add("has_package")

    relative_paths: list[ManifestRelativePath] = []
    bins = _sequence(root.get("bin"))
    if bins is not None:
        flags.add("has_bin_table")
        for bin_entry in bins:
            bin_mapping = _mapping(bin_entry)
            if bin_mapping is None or "path" not in bin_mapping:
                continue
            raw_path = bin_mapping["path"]
            safe_path = (
                _safe_relative_manifest_path(raw_path, limits.max_path_length)
                if isinstance(raw_path, str)
                else None
            )
            if safe_path is None:
                warnings.append(
                    _warning(
                        InventoryWarningCode.UNSAFE_MANIFEST_VALUE,
                        relative_path,
                        "The manifest contains an unsafe value.",
                    )
                )
            else:
                relative_paths.append(ManifestRelativePath("cargo_bin", safe_path))

    return (
        _fact("cargo_toml", relative_path, names, flags, relative_paths),
        tuple(warnings),
    )


def _parse_requirements(
    text: str,
    relative_path: str,
    _limits: InventoryLimits,
) -> tuple[ManifestFact | None, tuple[InventoryWarning, ...]]:
    names: set[str] = set()
    warnings: list[InventoryWarning] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if " #" in line:
            line = line.split(" #", maxsplit=1)[0].rstrip()
        name = _parse_requirement_name(line)
        if name is None:
            warnings.append(_skipped_warning(relative_path))
        else:
            names.add(name)
    return _fact("requirements_txt", relative_path, names), tuple(warnings)


def _parse_pom(
    text: str,
    relative_path: str,
    limits: InventoryLimits,
) -> tuple[ManifestFact | None, tuple[InventoryWarning, ...]]:
    root = _load_xml(text, relative_path, limits)
    names: set[str] = set()
    warnings: list[InventoryWarning] = []
    for element in root.iter():
        tag = _local_xml_name(element.tag)
        if tag not in {"dependency", "plugin", "parent"}:
            continue
        group_id = _child_text(element, "groupId")
        artifact_id = _child_text(element, "artifactId")
        if group_id is None or artifact_id is None:
            continue
        coordinate = f"{group_id}:{artifact_id}"
        if _safe_name(coordinate) is None:
            warnings.append(_skipped_warning(relative_path))
        else:
            names.add(coordinate.casefold())
    return _fact("pom_xml", relative_path, names), tuple(warnings)


def _parse_csproj(
    text: str,
    relative_path: str,
    limits: InventoryLimits,
) -> tuple[ManifestFact | None, tuple[InventoryWarning, ...]]:
    root = _load_xml(text, relative_path, limits)
    names: set[str] = set()
    warnings: list[InventoryWarning] = []
    sdk = _xml_attribute(root, "Sdk")
    if sdk is not None:
        safe_sdk = _safe_name(sdk)
        if safe_sdk is None:
            warnings.append(_skipped_warning(relative_path))
        else:
            names.add(safe_sdk.casefold())

    for element in root.iter():
        if _local_xml_name(element.tag) not in {"PackageReference", "FrameworkReference"}:
            continue
        raw_name = _xml_attribute(element, "Include") or _xml_attribute(element, "Update")
        if raw_name is None:
            continue
        safe_name = _safe_name(raw_name)
        if safe_name is None:
            warnings.append(_skipped_warning(relative_path))
        else:
            names.add(safe_name.casefold())
    return _fact("csproj", relative_path, names), tuple(warnings)


def _parse_gradle(
    text: str,
    relative_path: str,
    _limits: InventoryLimits,
) -> tuple[ManifestFact | None, tuple[InventoryWarning, ...]]:
    flags: set[str] = set()
    if GRADLE_SPRING_BOOT_PATTERN.search(text):
        flags.add("spring_boot_plugin")
    if GRADLE_DEPENDENCY_MANAGEMENT_PATTERN.search(text):
        flags.add("spring_dependency_management_plugin")
    return _fact("gradle", relative_path, (), flags), ()


def _presence_fact(relative_path: str) -> ManifestFact | None:
    path = PurePosixPath(relative_path)
    name = path.name.casefold()
    kind: str | None = None
    if name == "go.mod":
        kind = "go_mod"
    elif name == "alembic.ini":
        kind = "alembic_ini"
    elif tuple(part.casefold() for part in path.parts[-2:]) == ("prisma", "schema.prisma"):
        kind = "prisma_schema"
    elif is_dockerfile(path.name):
        kind = "dockerfile"
    elif name in COMPOSE_NAMES:
        kind = "docker_compose"
    elif is_ci_path(relative_path):
        kind = "github_actions_workflow"
    return _fact(kind, relative_path, ()) if kind is not None else None


def _parser_presence_fact(relative_path: str) -> ManifestFact | None:
    if PurePosixPath(relative_path).name.casefold() == "cargo.toml":
        return _fact("cargo_toml_presence", relative_path, ())
    return None


def _load_json(text: str, relative_path: str, limits: InventoryLimits) -> object:
    try:
        value: object = json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        raise _parse_error(relative_path) from None
    _validate_object_limits(value, limits)
    return value


def _load_toml(
    text: str,
    relative_path: str,
    limits: InventoryLimits,
) -> dict[str, object]:
    try:
        value: object = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, RecursionError):
        raise _parse_error(relative_path) from None
    _validate_object_limits(value, limits)
    mapping = _mapping(value)
    if mapping is None:
        raise _parse_error(relative_path)
    return mapping


def _load_xml(
    text: str,
    relative_path: str,
    limits: InventoryLimits,
) -> element_tree.Element:
    folded = text.casefold()
    if "<!doctype" in folded or "<!entity" in folded:
        raise _unsafe_value_error(relative_path)
    try:
        root = element_tree.fromstring(text)
    except (element_tree.ParseError, RecursionError):
        raise _parse_error(relative_path) from None
    _validate_xml_limits(root, limits)
    return root


def _validate_object_limits(value: object, limits: InventoryLimits) -> None:
    node_count = 0
    pending: list[tuple[object, int]] = [(value, 1)]
    while pending:
        current, depth = pending.pop()
        if depth > limits.max_json_nesting_depth:
            raise _ManifestLimitError(_LimitKind.NESTING)
        node_count += 1
        if node_count > limits.max_manifest_nodes:
            raise _ManifestLimitError(_LimitKind.NODES)
        mapping = _mapping(current)
        if mapping is not None:
            node_count += len(mapping)
            if node_count > limits.max_manifest_nodes:
                raise _ManifestLimitError(_LimitKind.NODES)
            pending.extend((child, depth + 1) for child in mapping.values())
            continue
        sequence = _sequence(current)
        if sequence is not None:
            pending.extend((child, depth + 1) for child in sequence)


def _validate_xml_limits(root: element_tree.Element, limits: InventoryLimits) -> None:
    node_count = 0
    pending = [(root, 1)]
    while pending:
        element, depth = pending.pop()
        if depth > limits.max_json_nesting_depth:
            raise _ManifestLimitError(_LimitKind.NESTING)
        node_count += 1 + len(element.attrib)
        if node_count > limits.max_manifest_nodes:
            raise _ManifestLimitError(_LimitKind.NODES)
        pending.extend((child, depth + 1) for child in element)


def _collect_requirement_list(
    value: object,
    names: set[str],
    warnings: list[InventoryWarning],
    relative_path: str,
) -> None:
    sequence = _sequence(value)
    if sequence is None:
        return
    for raw_requirement in sequence:
        name = (
            _parse_requirement_name(raw_requirement) if isinstance(raw_requirement, str) else None
        )
        if name is None:
            warnings.append(_skipped_warning(relative_path))
        else:
            names.add(name)


def _collect_mapping_keys(
    value: object,
    names: set[str],
    warnings: list[InventoryWarning],
    relative_path: str,
    *,
    python: bool,
) -> None:
    mapping = _mapping(value)
    if mapping is None:
        return
    for raw_name in mapping:
        name = _normalize_python_name(raw_name) if python else _normalize_package_name(raw_name)
        if name is None:
            warnings.append(_skipped_warning(relative_path))
        else:
            names.add(name)


def _parse_requirement_name(requirement: str) -> str | None:
    stripped = requirement.strip()
    folded = stripped.casefold()
    if (
        not stripped
        or stripped.startswith("-")
        or "://" in folded
        or folded.startswith(("git+", "hg+", "svn+", "bzr+"))
        or " @ " in stripped
        or "/" in stripped
        or "\\" in stripped
        or folded.endswith((".whl", ".zip", ".tar", ".tar.gz"))
    ):
        return None
    match = PYTHON_REQUIREMENT_PATTERN.fullmatch(stripped)
    if match is None:
        return None
    return _normalize_python_name(match.group("name"))


def _normalize_python_name(name: str) -> str | None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        return None
    return re.sub(r"[-_.]+", "-", name).casefold()


def _normalize_package_name(name: str) -> str | None:
    normalized = name.casefold()
    return normalized if PACKAGE_NAME_PATTERN.fullmatch(normalized) else None


def _safe_name(value: str) -> str | None:
    stripped = value.strip()
    if (
        not SAFE_NAME_PATTERN.fullmatch(stripped)
        or "://" in stripped
        or "\\" in stripped
        or "\x00" in stripped
    ):
        return None
    return stripped


def _safe_relative_manifest_path(value: object, max_length: int) -> str | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    if "\\" in value or "\x00" in value or "://" in value or ":" in value or value.endswith("/"):
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts:
        return None
    if any(part in {"", ".", ".."} for part in path.parts):
        return None
    normalized = path.as_posix()
    if len(normalized) > max_length:
        return None
    try:
        normalized.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return None
    return normalized


def _mapping(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return None
    return cast(dict[str, object], value)


def _sequence(value: object) -> list[object] | None:
    if not isinstance(value, list):
        return None
    return cast(list[object], value)


def _local_xml_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1].rsplit(":", maxsplit=1)[-1]


def _child_text(element: element_tree.Element, name: str) -> str | None:
    for child in element:
        if _local_xml_name(child.tag) == name and child.text is not None:
            value = child.text.strip()
            return value or None
    return None


def _xml_attribute(element: element_tree.Element, name: str) -> str | None:
    folded = name.casefold()
    for key, value in element.attrib.items():
        if _local_xml_name(key).casefold() == folded:
            stripped = value.strip()
            return stripped or None
    return None


def _fact(
    kind: str,
    relative_path: str,
    names: Iterable[str],
    metadata_flags: Iterable[str] = (),
    relative_paths: Iterable[ManifestRelativePath] = (),
) -> ManifestFact:
    return ManifestFact(
        kind=kind,
        relative_path=relative_path,
        names=tuple(sorted(set(names), key=lambda item: (item.casefold(), item))),
        metadata_flags=tuple(sorted(set(metadata_flags))),
        relative_paths=tuple(
            sorted(
                set(relative_paths),
                key=lambda item: (item.kind, *path_sort_key(item.relative_path)),
            )
        ),
    )


def _warning(
    code: InventoryWarningCode,
    relative_path: str,
    message: str,
) -> InventoryWarning:
    return InventoryWarning(code=code, relative_path=relative_path, message=message)


def _skipped_warning(relative_path: str) -> InventoryWarning:
    return _warning(
        InventoryWarningCode.MANIFEST_ENTRY_SKIPPED,
        relative_path,
        "A manifest entry was skipped because it was not safely supported.",
    )


def _limit_warning(kind: _LimitKind, relative_path: str) -> InventoryWarning:
    if kind is _LimitKind.NESTING:
        return _warning(
            InventoryWarningCode.MANIFEST_NESTING_LIMIT_EXCEEDED,
            relative_path,
            "The manifest exceeds the allowed nesting depth.",
        )
    return _warning(
        InventoryWarningCode.MANIFEST_NODE_LIMIT_EXCEEDED,
        relative_path,
        "The manifest exceeds the allowed node count.",
    )


def _parse_error(relative_path: str) -> _ManifestParseError:
    return _ManifestParseError(relative_path, unsafe=False)


def _unsafe_value_error(relative_path: str) -> _ManifestParseError:
    return _ManifestParseError(relative_path, unsafe=True)


class _ManifestParseError(Exception):
    def __init__(self, relative_path: str, *, unsafe: bool) -> None:
        super().__init__()
        self.relative_path = relative_path
        self.unsafe = unsafe
