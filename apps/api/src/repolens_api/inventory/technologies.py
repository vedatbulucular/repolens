"""Evidence-only deterministic technology detection."""

from dataclasses import dataclass
from pathlib import PurePosixPath

from repolens_api.inventory.contracts import (
    FindingConfidence,
    InventoryLimits,
    InventoryWarning,
    InventoryWarningCode,
    ManifestFact,
    TechnologyEvidence,
    TechnologyFinding,
)
from repolens_api.inventory.policy import path_sort_key

JAVASCRIPT_TECHNOLOGIES: dict[str, tuple[str, str]] = {
    "react": ("React", "library"),
    "next": ("Next.js", "framework"),
    "vue": ("Vue", "framework"),
    "@angular/core": ("Angular", "framework"),
    "express": ("Express", "framework"),
}
PYTHON_TECHNOLOGIES: dict[str, tuple[str, str]] = {
    "fastapi": ("FastAPI", "framework"),
    "django": ("Django", "framework"),
    "flask": ("Flask", "framework"),
    "pytest": ("pytest", "tooling"),
    "sqlalchemy": ("SQLAlchemy", "library"),
}


@dataclass(frozen=True, slots=True)
class TechnologyDetection:
    """Bounded technology findings plus a possible truncation warning."""

    findings: tuple[TechnologyFinding, ...]
    warnings: tuple[InventoryWarning, ...]


@dataclass(slots=True)
class _FindingBuilder:
    category: str
    evidence: dict[tuple[str, str], FindingConfidence]


def detect_technologies(
    facts: tuple[ManifestFact, ...],
    directories: tuple[str, ...],
    limits: InventoryLimits,
) -> TechnologyDetection:
    """Build findings only from structured facts and explicit presence signals."""
    builders: dict[str, _FindingBuilder] = {}
    for fact in facts:
        if fact.kind == "package_json":
            _detect_named(
                builders,
                fact,
                JAVASCRIPT_TECHNOLOGIES,
                evidence_type="package_dependency",
            )
        elif fact.kind in {"pyproject", "requirements_txt"}:
            _detect_named(
                builders,
                fact,
                PYTHON_TECHNOLOGIES,
                evidence_type="python_dependency",
            )
        elif fact.kind == "csproj" and _is_aspnet_core(fact):
            _add(
                builders,
                name="ASP.NET Core",
                category="framework",
                confidence=FindingConfidence.HIGH,
                evidence_type="dotnet_sdk_or_reference",
                relative_path=fact.relative_path,
            )
        elif fact.kind == "pom_xml" and any(
            name.startswith("org.springframework.boot:") for name in fact.names
        ):
            _add(
                builders,
                name="Spring Boot",
                category="framework",
                confidence=FindingConfidence.HIGH,
                evidence_type="maven_dependency_or_plugin",
                relative_path=fact.relative_path,
            )
        elif fact.kind == "gradle" and "spring_boot_plugin" in fact.metadata_flags:
            _add(
                builders,
                name="Spring Boot",
                category="framework",
                confidence=FindingConfidence.MEDIUM,
                evidence_type="bounded_gradle_pattern",
                relative_path=fact.relative_path,
            )
        elif fact.kind == "cargo_toml_presence":
            _add_presence(builders, "Rust/Cargo", "tooling", fact)
        elif fact.kind == "go_mod":
            _add_presence(builders, "Go Modules", "tooling", fact)
        elif fact.kind == "dockerfile":
            _add_presence(builders, "Docker", "infrastructure", fact)
        elif fact.kind == "docker_compose":
            _add_presence(builders, "Docker Compose", "infrastructure", fact)
        elif fact.kind == "github_actions_workflow":
            _add_presence(builders, "GitHub Actions", "ci", fact)
        elif fact.kind == "alembic_ini":
            _add_presence(builders, "Alembic", "tooling", fact)
        elif fact.kind == "prisma_schema":
            _add_presence(builders, "Prisma", "tooling", fact)

    _detect_alembic_directory(builders, directories)
    findings = tuple(
        sorted(
            (_build_finding(name, builder, limits) for name, builder in builders.items()),
            key=lambda finding: (finding.category, finding.name),
        )
    )
    if len(findings) <= limits.max_technology_findings:
        return TechnologyDetection(findings=findings, warnings=())
    return TechnologyDetection(
        findings=findings[: limits.max_technology_findings],
        warnings=(
            InventoryWarning(
                code=InventoryWarningCode.TECHNOLOGY_FINDING_LIMIT_REACHED,
                relative_path=None,
                message="Additional technology findings were omitted.",
            ),
        ),
    )


def _detect_named(
    builders: dict[str, _FindingBuilder],
    fact: ManifestFact,
    mappings: dict[str, tuple[str, str]],
    *,
    evidence_type: str,
) -> None:
    for dependency_name in fact.names:
        technology = mappings.get(dependency_name)
        if technology is None:
            continue
        name, category = technology
        _add(
            builders,
            name=name,
            category=category,
            confidence=FindingConfidence.HIGH,
            evidence_type=evidence_type,
            relative_path=fact.relative_path,
        )


def _is_aspnet_core(fact: ManifestFact) -> bool:
    return any(
        name == "microsoft.net.sdk.web"
        or name == "microsoft.aspnetcore.app"
        or name.startswith("microsoft.aspnetcore.")
        for name in fact.names
    )


def _add_presence(
    builders: dict[str, _FindingBuilder],
    name: str,
    category: str,
    fact: ManifestFact,
) -> None:
    _add(
        builders,
        name=name,
        category=category,
        confidence=FindingConfidence.MEDIUM,
        evidence_type="file_presence",
        relative_path=fact.relative_path,
    )


def _detect_alembic_directory(
    builders: dict[str, _FindingBuilder],
    directories: tuple[str, ...],
) -> None:
    folded = {directory.casefold(): directory for directory in directories}
    for directory in directories:
        path = PurePosixPath(directory)
        if path.name.casefold() != "alembic":
            continue
        versions = (path / "versions").as_posix().casefold()
        if versions not in folded:
            continue
        _add(
            builders,
            name="Alembic",
            category="tooling",
            confidence=FindingConfidence.MEDIUM,
            evidence_type="migration_directory_presence",
            relative_path=directory,
        )


def _add(
    builders: dict[str, _FindingBuilder],
    *,
    name: str,
    category: str,
    confidence: FindingConfidence,
    evidence_type: str,
    relative_path: str,
) -> None:
    builder = builders.setdefault(name, _FindingBuilder(category=category, evidence={}))
    key = (evidence_type, relative_path)
    existing = builder.evidence.get(key)
    if existing is None or confidence is FindingConfidence.HIGH:
        builder.evidence[key] = confidence


def _build_finding(
    name: str,
    builder: _FindingBuilder,
    limits: InventoryLimits,
) -> TechnologyFinding:
    ordered = tuple(
        TechnologyEvidence(evidence_type=evidence_type, relative_path=relative_path)
        for evidence_type, relative_path in sorted(
            builder.evidence,
            key=lambda item: (item[0], *path_sort_key(item[1])),
        )
    )
    confidence = (
        FindingConfidence.HIGH
        if FindingConfidence.HIGH in builder.evidence.values()
        else FindingConfidence.MEDIUM
    )
    return TechnologyFinding(
        name=name,
        category=builder.category,
        confidence=confidence,
        evidence=ordered[: limits.max_technology_evidence_per_finding],
        evidence_truncated=len(ordered) > limits.max_technology_evidence_per_finding,
    )
