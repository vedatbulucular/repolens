"""Tests for evidence-only deterministic technology detection."""

from dataclasses import replace

import pytest

from repolens_api.inventory.contracts import (
    FindingConfidence,
    InventoryLimits,
    InventoryWarningCode,
    ManifestFact,
)
from repolens_api.inventory.technologies import detect_technologies


def _manifest(
    kind: str,
    relative_path: str,
    *,
    names: tuple[str, ...] = (),
    flags: tuple[str, ...] = (),
) -> ManifestFact:
    return ManifestFact(
        kind=kind,
        relative_path=relative_path,
        names=names,
        metadata_flags=flags,
    )


@pytest.mark.parametrize(
    ("dependency", "expected_name"),
    [
        ("react", "React"),
        ("next", "Next.js"),
        ("vue", "Vue"),
        ("@angular/core", "Angular"),
        ("express", "Express"),
    ],
)
def test_javascript_dependencies_produce_high_confidence_findings(
    inventory_limits: InventoryLimits,
    dependency: str,
    expected_name: str,
) -> None:
    detection = detect_technologies(
        (_manifest("package_json", "package.json", names=(dependency,)),),
        (),
        inventory_limits,
    )

    assert detection.findings[0].name == expected_name
    assert detection.findings[0].confidence is FindingConfidence.HIGH
    assert detection.findings[0].evidence[0].evidence_type == "package_dependency"


@pytest.mark.parametrize(
    ("dependency", "expected_name"),
    [
        ("fastapi", "FastAPI"),
        ("django", "Django"),
        ("flask", "Flask"),
        ("pytest", "pytest"),
        ("sqlalchemy", "SQLAlchemy"),
    ],
)
def test_python_dependencies_produce_high_confidence_findings(
    inventory_limits: InventoryLimits,
    dependency: str,
    expected_name: str,
) -> None:
    detection = detect_technologies(
        (_manifest("requirements_txt", "requirements.txt", names=(dependency,)),),
        (),
        inventory_limits,
    )

    assert detection.findings[0].name == expected_name
    assert detection.findings[0].confidence is FindingConfidence.HIGH


def test_dotnet_maven_and_gradle_evidence_map_to_frameworks(
    inventory_limits: InventoryLimits,
) -> None:
    facts = (
        _manifest(
            "csproj",
            "src/App.csproj",
            names=("microsoft.net.sdk.web", "microsoft.aspnetcore.app"),
        ),
        _manifest(
            "pom_xml",
            "service/pom.xml",
            names=("org.springframework.boot:spring-boot-starter",),
        ),
        _manifest(
            "gradle",
            "other/build.gradle",
            flags=("spring_boot_plugin",),
        ),
    )

    detection = detect_technologies(facts, (), inventory_limits)
    findings = {finding.name: finding for finding in detection.findings}

    assert findings["ASP.NET Core"].confidence is FindingConfidence.HIGH
    assert findings["Spring Boot"].confidence is FindingConfidence.HIGH
    assert len(findings["Spring Boot"].evidence) == 2


@pytest.mark.parametrize(
    ("kind", "expected_name"),
    [
        ("cargo_toml_presence", "Rust/Cargo"),
        ("go_mod", "Go Modules"),
        ("dockerfile", "Docker"),
        ("docker_compose", "Docker Compose"),
        ("github_actions_workflow", "GitHub Actions"),
        ("alembic_ini", "Alembic"),
        ("prisma_schema", "Prisma"),
    ],
)
def test_presence_signals_produce_medium_confidence_findings(
    inventory_limits: InventoryLimits,
    kind: str,
    expected_name: str,
) -> None:
    detection = detect_technologies(
        (_manifest(kind, "evidence.file"),),
        (),
        inventory_limits,
    )

    assert detection.findings[0].name == expected_name
    assert detection.findings[0].confidence is FindingConfidence.MEDIUM
    assert detection.findings[0].evidence[0].evidence_type == "file_presence"


def test_safe_alembic_directory_signal_requires_versions_child(
    inventory_limits: InventoryLimits,
) -> None:
    positive = detect_technologies(
        (),
        ("services/api/alembic", "services/api/alembic/versions"),
        inventory_limits,
    )
    negative = detect_technologies(
        (),
        ("services/api/alembic",),
        inventory_limits,
    )

    assert positive.findings[0].name == "Alembic"
    assert positive.findings[0].evidence[0].relative_path == "services/api/alembic"
    assert negative.findings == ()


def test_duplicate_evidence_is_removed_sorted_and_truncated(
    inventory_limits: InventoryLimits,
) -> None:
    facts = (
        _manifest("package_json", "z/package.json", names=("react",)),
        _manifest("package_json", "a/package.json", names=("react",)),
        _manifest("package_json", "a/package.json", names=("react",)),
    )

    finding = detect_technologies(
        facts,
        (),
        replace(inventory_limits, max_technology_evidence_per_finding=1),
    ).findings[0]

    assert len(finding.evidence) == 1
    assert finding.evidence[0].relative_path == "a/package.json"
    assert finding.evidence_truncated is True


def test_finding_limit_uses_category_name_order_and_safe_warning(
    inventory_limits: InventoryLimits,
) -> None:
    facts = (
        _manifest("package_json", "package.json", names=("react", "next")),
        _manifest("dockerfile", "Dockerfile"),
    )

    detection = detect_technologies(
        facts,
        (),
        replace(inventory_limits, max_technology_findings=2),
    )

    assert tuple((item.category, item.name) for item in detection.findings) == (
        ("framework", "Next.js"),
        ("infrastructure", "Docker"),
    )
    assert detection.warnings[0].code is InventoryWarningCode.TECHNOLOGY_FINDING_LIMIT_REACHED


def test_technology_contract_contains_no_dependency_values(
    inventory_limits: InventoryLimits,
) -> None:
    version_secret = "private-version-value"
    detection = detect_technologies(
        (_manifest("pyproject", "pyproject.toml", names=("fastapi",)),),
        (),
        inventory_limits,
    )

    assert version_secret not in repr(detection)
    assert "FastAPI" in repr(detection)
