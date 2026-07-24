"""Tests for bounded, allowlisted manifest fact extraction."""

import json
from dataclasses import replace
from pathlib import Path

from repolens_api.inventory.content import SafeContentReader
from repolens_api.inventory.contracts import (
    InventoryLimits,
    InventoryWarningCode,
    ManifestFact,
)
from repolens_api.inventory.manifests import ManifestExtraction, extract_manifest_facts
from repolens_api.inventory.scanner import RepositoryScanner


def _extract(repository_root: Path, limits: InventoryLimits) -> ManifestExtraction:
    files = RepositoryScanner(limits).scan(repository_root).files
    return extract_manifest_facts(
        repository_root,
        files,
        SafeContentReader(limits),
        limits,
    )


def _fact(extraction: ManifestExtraction, kind: str) -> ManifestFact:
    return next(fact for fact in extraction.facts if fact.kind == kind)


def test_package_json_extracts_only_names_flags_and_safe_main(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    version_secret = "9.9.9-private"
    script_secret = "run-private-command --token secret"
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {"React": version_secret},
                "devDependencies": {"next": "canary-private"},
                "peerDependencies": {"vue": "private"},
                "optionalDependencies": {"express": "private"},
                "scripts": {"start": script_secret, "test": "another-private-command"},
                "main": "dist/index.js",
                "privateConfig": {"url": "https://private.invalid"},
            }
        ),
        encoding="utf-8",
    )

    extraction = _extract(tmp_path, inventory_limits)
    fact = _fact(extraction, "package_json")

    assert fact.names == ("express", "next", "react", "vue")
    assert fact.metadata_flags == ("has_start_script", "has_test_script")
    assert tuple((item.kind, item.relative_path) for item in fact.relative_paths) == (
        ("node_main", "dist/index.js"),
    )
    assert version_secret not in repr(extraction)
    assert script_secret not in repr(extraction)
    assert "private.invalid" not in repr(extraction)


def test_package_json_rejects_unsafe_main_paths(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    for raw_main in ("../outside.js", "/absolute.js", r"src\index.js", "C:/private.js"):
        (tmp_path / "package.json").write_text(
            json.dumps({"main": raw_main}),
            encoding="utf-8",
        )

        extraction = _extract(tmp_path, inventory_limits)

        assert _fact(extraction, "package_json").relative_paths == ()
        assert extraction.warnings[0].code is InventoryWarningCode.UNSAFE_MANIFEST_VALUE


def test_malformed_and_non_object_json_produce_fixed_safe_warnings(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    secret = "unexpected private parser input"
    (tmp_path / "package.json").write_text(f'{{"{secret}":', encoding="utf-8")
    malformed = _extract(tmp_path, inventory_limits)
    (tmp_path / "package.json").write_text("[]", encoding="utf-8")
    non_object = _extract(tmp_path, inventory_limits)

    assert malformed.warnings[0].code is InventoryWarningCode.MANIFEST_PARSE_FAILED
    assert non_object.warnings[0].code is InventoryWarningCode.MANIFEST_PARSE_FAILED
    assert secret not in repr(malformed.warnings)


def test_json_nesting_node_and_byte_limits_are_non_fatal(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    path = tmp_path / "package.json"
    path.write_text('{"a":{"b":{"c":1}}}', encoding="utf-8")
    nesting = _extract(
        tmp_path,
        replace(inventory_limits, max_json_nesting_depth=2),
    )
    path.write_text('{"unused":[1,2,3,4]}', encoding="utf-8")
    nodes = _extract(
        tmp_path,
        replace(inventory_limits, max_manifest_nodes=4),
    )
    path.write_text('{"dependencies":{"react":"private"}}', encoding="utf-8")
    oversized = _extract(
        tmp_path,
        replace(inventory_limits, max_manifest_bytes=10),
    )

    assert nesting.warnings[0].code is InventoryWarningCode.MANIFEST_NESTING_LIMIT_EXCEEDED
    assert nodes.warnings[0].code is InventoryWarningCode.MANIFEST_NODE_LIMIT_EXCEEDED
    assert oversized.warnings[0].code is InventoryWarningCode.MANIFEST_TOO_LARGE


def test_json_rejects_nul_and_non_utf8_content(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    path = tmp_path / "package.json"
    path.write_bytes(b'{"name":"unsafe\x00value"}')
    nul = _extract(tmp_path, inventory_limits)
    path.write_bytes(b'{"name":"\xff"}')
    encoding = _extract(tmp_path, inventory_limits)

    assert nul.warnings[0].code is InventoryWarningCode.UNSAFE_MANIFEST_VALUE
    assert encoding.warnings[0].code is InventoryWarningCode.UNSUPPORTED_FILE_ENCODING


def test_pyproject_collects_supported_dependency_sources_without_versions(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    version_secret = "42.0-private"
    (tmp_path / "pyproject.toml").write_text(
        f"""
[project]
dependencies = ["FastAPI>={version_secret}", "SQLAlchemy[asyncio]~=2"]

[project.optional-dependencies]
test = ["Py_Test==8"]

[tool.poetry.dependencies]
python = "^3.12"
Flask = "{version_secret}"

[tool.poetry.group.dev.dependencies]
Django = "{version_secret}"

[dependency-groups]
lint = ["Ruff=={version_secret}"]

[build-system]
requires = ["hatchling>={version_secret}"]
""",
        encoding="utf-8",
    )

    extraction = _extract(tmp_path, inventory_limits)
    fact = _fact(extraction, "pyproject")

    assert fact.names == (
        "django",
        "fastapi",
        "flask",
        "hatchling",
        "py-test",
        "python",
        "ruff",
        "sqlalchemy",
    )
    assert version_secret not in repr(extraction)


def test_malformed_toml_does_not_expose_parser_input(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    secret = "private-invalid-value"
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\ndependencies = ["{secret}"',
        encoding="utf-8",
    )

    extraction = _extract(tmp_path, inventory_limits)

    assert extraction.warnings[0].code is InventoryWarningCode.MANIFEST_PARSE_FAILED
    assert secret not in repr(extraction.warnings)


def test_cargo_extracts_dependency_names_and_safe_bin_paths(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    version_secret = "private-version"
    (tmp_path / "Cargo.toml").write_text(
        f"""
[package]
name = "sample"

[dependencies]
serde = "{version_secret}"

[dev-dependencies]
tokio-test = "{version_secret}"

[build-dependencies]
cc = "{version_secret}"

[[bin]]
name = "worker"
path = "src/worker.rs"
""",
        encoding="utf-8",
    )

    extraction = _extract(tmp_path, inventory_limits)
    fact = _fact(extraction, "cargo_toml")

    assert fact.names == ("cc", "serde", "tokio-test")
    assert fact.metadata_flags == ("has_bin_table", "has_package")
    assert fact.relative_paths[0].relative_path == "src/worker.rs"
    assert version_secret not in repr(extraction)
    assert _fact(extraction, "cargo_toml_presence").relative_path == "Cargo.toml"


def test_requirements_normalizes_plain_names_and_skips_unsafe_lines(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "requirements.txt").write_text(
        """
# comment
FastAPI[standard]>=0.100
SQLAlchemy~=2
my_package.name==1
-r included.txt
--index-url https://private.invalid/simple
-e ../local-package
git+https://private.invalid/project.git
https://private.invalid/archive.whl
""",
        encoding="utf-8",
    )
    (tmp_path / "included.txt").write_text("Django==5", encoding="utf-8")

    extraction = _extract(tmp_path, inventory_limits)
    fact = _fact(extraction, "requirements_txt")

    assert fact.names == ("fastapi", "my-package-name", "sqlalchemy")
    assert any(
        warning.code is InventoryWarningCode.MANIFEST_ENTRY_SKIPPED
        for warning in extraction.warnings
    )
    assert "django" not in fact.names
    assert "private.invalid" not in repr(extraction)


def test_pom_namespace_collects_dependency_plugin_and_parent_coordinates(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "pom.xml").write_text(
        """
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent><groupId>org.springframework.boot</groupId><artifactId>parent</artifactId></parent>
  <dependencies>
    <dependency><groupId>org.example</groupId><artifactId>library</artifactId></dependency>
  </dependencies>
  <build><plugins>
    <plugin><groupId>org.springframework.boot</groupId><artifactId>plugin</artifactId></plugin>
  </plugins></build>
</project>
""",
        encoding="utf-8",
    )

    fact = _fact(_extract(tmp_path, inventory_limits), "pom_xml")

    assert fact.names == (
        "org.example:library",
        "org.springframework.boot:parent",
        "org.springframework.boot:plugin",
    )


def test_xml_rejects_doctype_entity_and_enforces_structure_limits(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    path = tmp_path / "pom.xml"
    path.write_text(
        '<!DOCTYPE project [<!ENTITY private SYSTEM "file:///private">]><project/>',
        encoding="utf-8",
    )
    unsafe = _extract(tmp_path, inventory_limits)
    path.write_text("<a><b><c/></b></a>", encoding="utf-8")
    nesting = _extract(tmp_path, replace(inventory_limits, max_json_nesting_depth=2))
    path.write_text("<a><b/><c/><d/></a>", encoding="utf-8")
    nodes = _extract(tmp_path, replace(inventory_limits, max_manifest_nodes=3))

    assert unsafe.warnings[0].code is InventoryWarningCode.UNSAFE_MANIFEST_VALUE
    assert nesting.warnings[0].code is InventoryWarningCode.MANIFEST_NESTING_LIMIT_EXCEEDED
    assert nodes.warnings[0].code is InventoryWarningCode.MANIFEST_NODE_LIMIT_EXCEEDED
    assert "file:///private" not in repr(unsafe)


def test_csproj_extracts_sdk_and_reference_names_without_versions(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    version_secret = "9.0-private"
    (tmp_path / "Sample.csproj").write_text(
        f"""
<Project Sdk="Microsoft.NET.Sdk.Web">
  <ItemGroup>
    <PackageReference Include="Microsoft.AspNetCore.Mvc" Version="{version_secret}" />
    <FrameworkReference Update="Microsoft.AspNetCore.App" />
  </ItemGroup>
</Project>
""",
        encoding="utf-8",
    )

    fact = _fact(_extract(tmp_path, inventory_limits), "csproj")

    assert fact.names == (
        "microsoft.aspnetcore.app",
        "microsoft.aspnetcore.mvc",
        "microsoft.net.sdk.web",
    )
    assert version_secret not in repr(fact)


def test_gradle_uses_only_allowlisted_literal_plugin_patterns(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "build.gradle.kts").write_text(
        """
plugins {
    id("org.springframework.boot") version "private-version"
    id("io.spring.dependency-management")
}
val ignored = "org.springframework.boot"
""",
        encoding="utf-8",
    )

    fact = _fact(_extract(tmp_path, inventory_limits), "gradle")

    assert fact.metadata_flags == (
        "spring_boot_plugin",
        "spring_dependency_management_plugin",
    )
    assert "private-version" not in repr(fact)


def test_presence_facts_require_no_manifest_parsing(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    paths = (
        "go.mod",
        "alembic.ini",
        "prisma/schema.prisma",
        "Dockerfile",
        "compose.yaml",
        ".github/workflows/ci.yml",
    )
    for relative_path in paths:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("unparsed private content", encoding="utf-8")

    extraction = _extract(tmp_path, inventory_limits)

    assert {fact.kind for fact in extraction.facts} == {
        "alembic_ini",
        "docker_compose",
        "dockerfile",
        "github_actions_workflow",
        "go_mod",
        "prisma_schema",
    }
    assert "unparsed private content" not in repr(extraction)


def test_broken_manifest_does_not_stop_other_fact_detection(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "package.json").write_text("{", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("private body", encoding="utf-8")

    extraction = _extract(tmp_path, inventory_limits)

    assert tuple(fact.kind for fact in extraction.facts) == ("dockerfile",)
    assert extraction.warnings[0].code is InventoryWarningCode.MANIFEST_PARSE_FAILED
