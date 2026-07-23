"""Conservative entry-point detection without ASTs or command interpretation."""

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from repolens_api.inventory.content import SafeContentReader
from repolens_api.inventory.contracts import (
    ContentStatus,
    EntryPointFinding,
    FileInventoryEntry,
    FindingConfidence,
    InventoryLimits,
    InventoryWarning,
    InventoryWarningCode,
    ManifestFact,
    TechnologyFinding,
)
from repolens_api.inventory.policy import is_test_directory_path, path_sort_key

SPRING_ANNOTATION_PATTERN = re.compile(r"@SpringBootApplication\b")
JAVA_MAIN_PATTERN = re.compile(r"\bpublic\s+static\s+void\s+main\s*\(")
GO_MAIN_PATTERN = re.compile(r"(?m)^\s*package\s+main\b")
PYTHON_ENTRY_NAMES = frozenset({"main.py", "app.py", "manage.py"})
NEXT_DIRECTORIES = ("app", "pages", "src/app", "src/pages")


@dataclass(frozen=True, slots=True)
class EntryPointDetection:
    """Bounded entry-point findings and safe read warnings."""

    findings: tuple[EntryPointFinding, ...]
    warnings: tuple[InventoryWarning, ...]


def detect_entry_points(
    repository_root: Path,
    files: tuple[FileInventoryEntry, ...],
    directories: tuple[str, ...],
    manifests: tuple[ManifestFact, ...],
    technologies: tuple[TechnologyFinding, ...],
    content_reader: SafeContentReader,
    limits: InventoryLimits,
) -> EntryPointDetection:
    """Detect explicit manifest paths and conservative bounded text signals."""
    candidates: dict[tuple[str, str], EntryPointFinding] = {}
    warnings: list[InventoryWarning] = []
    file_paths = {entry.relative_path for entry in files}
    directory_paths = set(directories)

    for entry in files:
        name = PurePosixPath(entry.relative_path).name
        if name.casefold() in PYTHON_ENTRY_NAMES and not is_test_directory_path(
            entry.relative_path
        ):
            _add(
                candidates,
                kind="python_module",
                relative_path=entry.relative_path,
                confidence=FindingConfidence.MEDIUM,
                evidence_type="filename_convention",
            )
        if name.casefold() == "program.cs":
            _add(
                candidates,
                kind="dotnet_program",
                relative_path=entry.relative_path,
                confidence=FindingConfidence.MEDIUM,
                evidence_type="filename_convention",
            )

    for manifest in manifests:
        if manifest.kind == "package_json":
            _detect_node_main(candidates, manifest, file_paths)
        elif manifest.kind == "cargo_toml":
            _detect_rust_entries(candidates, manifest, file_paths)

    _detect_next_directories(candidates, technologies, directory_paths)
    text_warnings = _detect_bounded_text_entries(
        candidates,
        repository_root,
        files,
        content_reader,
        limits,
    )
    warnings.extend(text_warnings)

    ordered = tuple(
        sorted(
            candidates.values(),
            key=lambda finding: (finding.kind, *path_sort_key(finding.relative_path)),
        )
    )
    if len(ordered) <= limits.max_entry_points:
        return EntryPointDetection(findings=ordered, warnings=tuple(warnings))
    warnings.append(
        InventoryWarning(
            code=InventoryWarningCode.ENTRY_POINT_LIMIT_REACHED,
            relative_path=None,
            message="Additional entry-point findings were omitted.",
        )
    )
    return EntryPointDetection(
        findings=ordered[: limits.max_entry_points],
        warnings=tuple(warnings),
    )


def _detect_node_main(
    candidates: dict[tuple[str, str], EntryPointFinding],
    manifest: ManifestFact,
    file_paths: set[str],
) -> None:
    package_root = PurePosixPath(manifest.relative_path).parent
    for path_fact in manifest.relative_paths:
        if path_fact.kind != "node_main":
            continue
        candidate = (package_root / path_fact.relative_path).as_posix()
        if candidate not in file_paths:
            continue
        _add(
            candidates,
            kind="node_main",
            relative_path=candidate,
            confidence=FindingConfidence.HIGH,
            evidence_type="package_json_main",
        )


def _detect_next_directories(
    candidates: dict[tuple[str, str], EntryPointFinding],
    technologies: tuple[TechnologyFinding, ...],
    directory_paths: set[str],
) -> None:
    next_finding = next((finding for finding in technologies if finding.name == "Next.js"), None)
    if next_finding is None:
        return
    package_roots = {
        PurePosixPath(evidence.relative_path).parent
        for evidence in next_finding.evidence
        if PurePosixPath(evidence.relative_path).name.casefold() == "package.json"
    }
    for package_root in package_roots:
        for relative_directory in NEXT_DIRECTORIES:
            candidate = (package_root / relative_directory).as_posix()
            if candidate not in directory_paths:
                continue
            _add(
                candidates,
                kind="nextjs_route_directory",
                relative_path=candidate,
                confidence=FindingConfidence.MEDIUM,
                evidence_type="directory_presence",
            )


def _detect_rust_entries(
    candidates: dict[tuple[str, str], EntryPointFinding],
    manifest: ManifestFact,
    file_paths: set[str],
) -> None:
    package_root = PurePosixPath(manifest.relative_path).parent
    conventional = (package_root / "src/main.rs").as_posix()
    if conventional in file_paths:
        _add(
            candidates,
            kind="rust_binary",
            relative_path=conventional,
            confidence=FindingConfidence.MEDIUM,
            evidence_type="cargo_convention",
        )
    for path_fact in manifest.relative_paths:
        if path_fact.kind != "cargo_bin":
            continue
        candidate = (package_root / path_fact.relative_path).as_posix()
        if candidate not in file_paths:
            continue
        _add(
            candidates,
            kind="rust_binary",
            relative_path=candidate,
            confidence=FindingConfidence.HIGH,
            evidence_type="cargo_bin_path",
        )


def _detect_bounded_text_entries(
    candidates: dict[tuple[str, str], EntryPointFinding],
    repository_root: Path,
    files: tuple[FileInventoryEntry, ...],
    content_reader: SafeContentReader,
    limits: InventoryLimits,
) -> tuple[InventoryWarning, ...]:
    warnings: list[InventoryWarning] = []
    for entry in files:
        if (
            entry.content_status is not ContentStatus.AVAILABLE
            or entry.is_binary is not False
            or entry.size_bytes > limits.max_text_read_bytes
        ):
            continue
        if entry.extension not in {".java", ".go"}:
            continue
        result = content_reader.read_text(
            repository_root,
            entry.relative_path,
            expected_size=entry.size_bytes,
            max_bytes=limits.max_text_read_bytes,
        )
        if result.warning is not None:
            warnings.append(result.warning)
        if result.text is None:
            continue
        if entry.extension == ".java" and (
            SPRING_ANNOTATION_PATTERN.search(result.text) and JAVA_MAIN_PATTERN.search(result.text)
        ):
            _add(
                candidates,
                kind="spring_boot_application",
                relative_path=entry.relative_path,
                confidence=FindingConfidence.MEDIUM,
                evidence_type="bounded_text_pattern",
            )
        elif entry.extension == ".go" and GO_MAIN_PATTERN.search(result.text):
            _add(
                candidates,
                kind="go_main_package",
                relative_path=entry.relative_path,
                confidence=FindingConfidence.MEDIUM,
                evidence_type="bounded_text_pattern",
            )
    return tuple(warnings)


def _add(
    candidates: dict[tuple[str, str], EntryPointFinding],
    *,
    kind: str,
    relative_path: str,
    confidence: FindingConfidence,
    evidence_type: str,
) -> None:
    key = (kind, relative_path)
    finding = EntryPointFinding(
        kind=kind,
        relative_path=relative_path,
        confidence=confidence,
        evidence_type=evidence_type,
    )
    existing = candidates.get(key)
    if existing is None:
        candidates[key] = finding
        return
    if (
        existing.confidence is FindingConfidence.MEDIUM and confidence is FindingConfidence.HIGH
    ) or (existing.confidence is confidence and evidence_type < existing.evidence_type):
        candidates[key] = finding
