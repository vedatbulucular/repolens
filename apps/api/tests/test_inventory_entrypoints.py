"""Tests for conservative AST-free entry-point detection."""

import json
from dataclasses import replace
from pathlib import Path

from repolens_api.inventory.contracts import (
    FindingConfidence,
    InventoryLimits,
    InventoryWarningCode,
)
from repolens_api.inventory.service import InventoryService


def test_python_entry_files_exclude_test_directories(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("private source", encoding="utf-8")
    (tmp_path / "app.py").write_text("private source", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "manage.py").write_text("private source", encoding="utf-8")

    result = InventoryService(inventory_limits).analyze(tmp_path)

    assert tuple((finding.kind, finding.relative_path) for finding in result.entry_points) == (
        ("python_module", "app.py"),
        ("python_module", "src/main.py"),
    )


def test_package_json_main_requires_safe_existing_inventory_path(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "packages" / "web" / "src").mkdir(parents=True)
    (tmp_path / "packages" / "web" / "src" / "index.js").write_text(
        "private source",
        encoding="utf-8",
    )
    (tmp_path / "packages" / "web" / "package.json").write_text(
        json.dumps({"main": "src/index.js"}),
        encoding="utf-8",
    )

    result = InventoryService(inventory_limits).analyze(tmp_path)

    assert result.entry_points[0].kind == "node_main"
    assert result.entry_points[0].relative_path == "packages/web/src/index.js"
    assert result.entry_points[0].confidence is FindingConfidence.HIGH


def test_package_json_main_rejects_unsafe_or_missing_paths(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    package = tmp_path / "package.json"
    package.write_text(json.dumps({"main": "../outside.js"}), encoding="utf-8")
    unsafe = InventoryService(inventory_limits).analyze(tmp_path)
    package.write_text(json.dumps({"main": "missing.js"}), encoding="utf-8")
    missing = InventoryService(inventory_limits).analyze(tmp_path)

    assert unsafe.entry_points == ()
    assert any(
        warning.code is InventoryWarningCode.UNSAFE_MANIFEST_VALUE for warning in unsafe.warnings
    )
    assert missing.entry_points == ()


def test_nextjs_directories_are_scoped_to_package_root(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    package_root = tmp_path / "packages" / "web"
    (package_root / "src" / "app").mkdir(parents=True)
    (package_root / "pages").mkdir()
    (tmp_path / "unrelated" / "app").mkdir(parents=True)
    (package_root / "package.json").write_text(
        json.dumps({"dependencies": {"next": "private-version"}}),
        encoding="utf-8",
    )

    result = InventoryService(inventory_limits).analyze(tmp_path)
    paths = tuple(finding.relative_path for finding in result.entry_points)

    assert paths == ("packages/web/pages", "packages/web/src/app")
    assert "unrelated/app" not in paths


def test_program_cs_matching_is_case_insensitive(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "PROGRAM.CS").write_text("private source", encoding="utf-8")

    result = InventoryService(inventory_limits).analyze(tmp_path)

    assert result.entry_points[0].kind == "dotnet_program"
    assert result.entry_points[0].relative_path == "PROGRAM.CS"


def test_java_requires_both_spring_annotation_and_main_signal(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "Application.java").write_text(
        """
@SpringBootApplication
class Application {
    public static void main(String[] args) {}
}
""",
        encoding="utf-8",
    )
    (tmp_path / "OnlyMain.java").write_text(
        "class OnlyMain { public static void main(String[] args) {} }",
        encoding="utf-8",
    )

    result = InventoryService(inventory_limits).analyze(tmp_path)

    assert tuple(
        finding.relative_path
        for finding in result.entry_points
        if finding.kind == "spring_boot_application"
    ) == ("Application.java",)


def test_go_package_main_is_detected_from_bounded_text(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "cmd").mkdir()
    (tmp_path / "cmd" / "main.go").write_text(
        "package main\n\nfunc main() {}\n",
        encoding="utf-8",
    )
    (tmp_path / "library.go").write_text("package library\n", encoding="utf-8")

    result = InventoryService(inventory_limits).analyze(tmp_path)

    assert tuple(
        finding.relative_path
        for finding in result.entry_points
        if finding.kind == "go_main_package"
    ) == ("cmd/main.go",)


def test_rust_convention_and_cargo_bin_path_are_deduplicated(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.rs").write_text("private source", encoding="utf-8")
    (tmp_path / "src" / "worker.rs").write_text("private source", encoding="utf-8")
    (tmp_path / "Cargo.toml").write_text(
        """
[package]
name = "sample"

[[bin]]
name = "main"
path = "src/main.rs"

[[bin]]
name = "worker"
path = "src/worker.rs"
""",
        encoding="utf-8",
    )

    result = InventoryService(inventory_limits).analyze(tmp_path)
    rust = tuple(finding for finding in result.entry_points if finding.kind == "rust_binary")

    assert tuple(finding.relative_path for finding in rust) == (
        "src/main.rs",
        "src/worker.rs",
    )
    assert all(finding.confidence is FindingConfidence.HIGH for finding in rust)


def test_entry_point_limit_deduplicates_and_truncates_deterministically(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    for name in ("manage.py", "main.py", "app.py"):
        (tmp_path / name).write_text("private source", encoding="utf-8")

    result = InventoryService(
        replace(inventory_limits, max_entry_points=2),
    ).analyze(tmp_path)

    assert tuple((finding.kind, finding.relative_path) for finding in result.entry_points) == (
        ("python_module", "app.py"),
        ("python_module", "main.py"),
    )
    assert any(
        warning.code is InventoryWarningCode.ENTRY_POINT_LIMIT_REACHED
        for warning in result.warnings
    )


def test_entry_points_are_deterministic_and_never_contain_script_commands(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    script_secret = "node private-command --token secret"
    (tmp_path / "index.js").write_text("private source body", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "main": "index.js",
                "scripts": {"start": script_secret},
            }
        ),
        encoding="utf-8",
    )
    service = InventoryService(inventory_limits)

    first = service.analyze(tmp_path)
    second = service.analyze(tmp_path)

    assert first == second
    assert script_secret not in repr(first)
    assert str(tmp_path) not in repr(first)
