"""Tests for explicit deterministic inventory result serialization."""

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from repolens_api.analysis_results import (
    AnalysisOutput,
    AnalysisResultErrorCode,
    AnalysisResultSerializationError,
    QualityAnalysisOutput,
    deterministic_json_bytes,
    prepare_inventory_result,
    serialize_inventory_result,
)
from repolens_api.inventory.contracts import InventoryResult
from repolens_api.quality_findings.contracts import QualityFindingCode


def test_serializer_emits_only_explicit_json_compatible_fields(
    inventory_result: InventoryResult,
) -> None:
    payload = serialize_inventory_result(inventory_result)

    assert set(payload) == {
        "repository_summary",
        "languages",
        "important_files",
        "technologies",
        "entry_points",
        "warnings",
    }
    assert "schema_version" not in payload
    assert isinstance(payload["languages"], list)
    assert isinstance(payload["important_files"], list)
    technologies = cast(list[dict[str, object]], payload["technologies"])
    entry_points = cast(list[dict[str, object]], payload["entry_points"])
    warnings = cast(list[dict[str, object]], payload["warnings"])
    assert technologies[0]["confidence"] == "high"
    assert entry_points[0]["confidence"] == "medium"
    assert warnings[0]["code"] == "file_unreadable"


def test_version_two_serializer_adds_only_typed_code_structure(
    analysis_output: AnalysisOutput,
) -> None:
    payload = serialize_inventory_result(analysis_output)

    assert set(payload) == {
        "repository_summary",
        "languages",
        "important_files",
        "technologies",
        "entry_points",
        "warnings",
        "code_structure",
    }
    structure = cast(dict[str, object], payload["code_structure"])
    assert set(structure) == {"summary", "files", "symbols", "imports", "warnings"}
    symbols = cast(list[dict[str, object]], structure["symbols"])
    imports = cast(list[dict[str, object]], structure["imports"])
    assert symbols[0] == {
        "relative_path": "src/main.py",
        "language": "Python",
        "kind": "function",
        "name": "create_app",
        "qualified_name": "create_app",
        "start_line": 3,
        "end_line": 4,
        "parent_name": None,
        "parameter_count": 0,
        "is_exported": False,
        "is_public": True,
    }
    assert imports[0]["module"] == "fastapi"
    assert imports[0]["imported_names"] == ["FastAPI"]


def test_version_three_serializer_adds_typed_quality_findings(
    quality_analysis_output: QualityAnalysisOutput,
) -> None:
    payload = serialize_inventory_result(quality_analysis_output)

    assert set(payload) == {
        "repository_summary",
        "languages",
        "important_files",
        "technologies",
        "entry_points",
        "warnings",
        "code_structure",
        "quality_findings",
    }
    quality = cast(dict[str, object], payload["quality_findings"])
    findings = cast(list[dict[str, object]], quality["findings"])
    evidence = cast(list[dict[str, object]], findings[0]["evidence"])
    assert findings[0]["code"] == QualityFindingCode.DOCUMENTATION_PRESENT.value
    assert findings[0]["related_paths"] == ["README.md"]
    assert evidence == [{"kind": "file_count", "value": 1}]
    assert quality["warnings"] == []


def test_deterministic_json_bytes_are_equal_for_the_same_logical_result(
    inventory_result: InventoryResult,
) -> None:
    first = prepare_inventory_result(inventory_result, max_result_bytes=10_000)
    second = prepare_inventory_result(inventory_result, max_result_bytes=10_000)

    assert first.payload == second.payload
    assert first.json_bytes == second.json_bytes
    assert first.json_bytes == deterministic_json_bytes(first.payload)


def test_version_two_serialization_is_deterministic(
    analysis_output: AnalysisOutput,
) -> None:
    first = prepare_inventory_result(analysis_output, max_result_bytes=20_000)
    second = prepare_inventory_result(analysis_output, max_result_bytes=20_000)

    assert first.schema_version == 2
    assert first.json_bytes == second.json_bytes


def test_version_three_serialization_is_deterministic(
    quality_analysis_output: QualityAnalysisOutput,
) -> None:
    first = prepare_inventory_result(quality_analysis_output, max_result_bytes=30_000)
    second = prepare_inventory_result(quality_analysis_output, max_result_bytes=30_000)

    assert first.schema_version == 3
    assert first.json_bytes == second.json_bytes


def test_legacy_result_cannot_claim_version_two_without_structure(
    inventory_result: InventoryResult,
) -> None:
    invalid = replace(inventory_result, schema_version=2)

    with pytest.raises(AnalysisResultSerializationError) as raised:
        prepare_inventory_result(invalid, max_result_bytes=10_000)

    assert raised.value.code is AnalysisResultErrorCode.RESULT_SERIALIZATION_FAILED


@pytest.mark.parametrize("percentage", [float("nan"), float("inf"), float("-inf")])
def test_serializer_rejects_non_finite_floats(
    inventory_result: InventoryResult,
    percentage: float,
) -> None:
    language = replace(inventory_result.languages[0], percentage=percentage)

    with pytest.raises(AnalysisResultSerializationError) as raised:
        serialize_inventory_result(replace(inventory_result, languages=(language,)))

    assert raised.value.code is AnalysisResultErrorCode.RESULT_SERIALIZATION_FAILED


@pytest.mark.parametrize("unsupported", [Path("private"), b"private", object()])
def test_serializer_rejects_path_bytes_and_arbitrary_objects(
    inventory_result: InventoryResult,
    unsupported: object,
) -> None:
    language = replace(
        inventory_result.languages[0],
        name=cast(str, unsupported),
    )

    with pytest.raises(AnalysisResultSerializationError) as raised:
        serialize_inventory_result(replace(inventory_result, languages=(language,)))

    assert raised.value.code is AnalysisResultErrorCode.RESULT_SERIALIZATION_FAILED
    assert "private" not in str(raised.value)


@pytest.mark.parametrize(
    "unsafe_path",
    ["/tmp/repolens-workspaces/private.py", r"C:\private\source.py", "../outside.py"],
)
def test_serializer_rejects_absolute_and_traversal_paths(
    inventory_result: InventoryResult,
    unsafe_path: str,
) -> None:
    entry_point = replace(
        inventory_result.entry_points[0],
        relative_path=unsafe_path,
    )

    with pytest.raises(AnalysisResultSerializationError):
        serialize_inventory_result(replace(inventory_result, entry_points=(entry_point,)))


def test_serializer_output_contains_no_forbidden_source_values(
    inventory_result: InventoryResult,
) -> None:
    serialized = prepare_inventory_result(
        inventory_result,
        max_result_bytes=10_000,
    ).json_bytes.decode("utf-8")

    for forbidden in (
        "processing-token-private",
        "run-server --token private",
        "dependency-version-private",
        "PRIVATE_SOURCE_BODY",
        "/tmp/repolens-workspaces",
        "C:\\private",
    ):
        assert forbidden not in serialized


def test_version_two_output_contains_no_source_bodies_or_system_paths(
    analysis_output: AnalysisOutput,
) -> None:
    serialized = prepare_inventory_result(
        analysis_output,
        max_result_bytes=20_000,
    ).json_bytes.decode("utf-8")

    for forbidden in (
        "PRIVATE_SOURCE_BODY",
        "processing-token-private",
        "/tmp/repolens-workspaces",
        r"C:\private",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "unsafe_path",
    ["/tmp/private.py", r"C:\private.py", "../outside.py"],
)
def test_version_two_serializer_rejects_unsafe_source_paths(
    analysis_output: AnalysisOutput,
    unsafe_path: str,
) -> None:
    structure = analysis_output.code_structure
    unsafe_file = replace(structure.files[0], relative_path=unsafe_path)
    unsafe_output = replace(
        analysis_output,
        code_structure=replace(structure, files=(unsafe_file,)),
    )

    with pytest.raises(AnalysisResultSerializationError):
        serialize_inventory_result(unsafe_output)


def test_version_two_serializer_rejects_non_contract_warning_message(
    analysis_output: AnalysisOutput,
) -> None:
    structure = analysis_output.code_structure
    unsafe_warning = replace(
        structure.warnings[0],
        message="PRIVATE parser exception and source line",
    )
    unsafe_output = replace(
        analysis_output,
        code_structure=replace(structure, warnings=(unsafe_warning,)),
    )

    with pytest.raises(AnalysisResultSerializationError):
        serialize_inventory_result(unsafe_output)


def test_version_three_serializer_rejects_non_contract_finding_text(
    quality_analysis_output: QualityAnalysisOutput,
) -> None:
    result = quality_analysis_output.quality_findings
    unsafe_finding = replace(result.findings[0], message="PRIVATE document content")
    unsafe_output = replace(
        quality_analysis_output,
        quality_findings=replace(result, findings=(unsafe_finding,)),
    )

    with pytest.raises(AnalysisResultSerializationError):
        serialize_inventory_result(unsafe_output)


@pytest.mark.parametrize(
    "unsafe_path",
    ["/tmp/private.md", r"C:\private.md", "../outside.md"],
)
def test_version_three_serializer_rejects_unsafe_quality_paths(
    quality_analysis_output: QualityAnalysisOutput,
    unsafe_path: str,
) -> None:
    result = quality_analysis_output.quality_findings
    finding = replace(result.findings[0], related_paths=(unsafe_path,))
    unsafe_output = replace(
        quality_analysis_output,
        quality_findings=replace(result, findings=(finding,)),
    )

    with pytest.raises(AnalysisResultSerializationError):
        serialize_inventory_result(unsafe_output)


def test_version_three_output_contains_no_document_content_or_tokens(
    quality_analysis_output: QualityAnalysisOutput,
) -> None:
    serialized = prepare_inventory_result(
        quality_analysis_output,
        max_result_bytes=30_000,
    ).json_bytes.decode("utf-8")

    for forbidden in (
        "PRIVATE README PARAGRAPH",
        "run-private-command --token secret",
        "processing-token-private",
        "/tmp/repolens-workspaces",
        r"C:\private",
    ):
        assert forbidden not in serialized


def test_result_size_limit_is_all_or_nothing(
    inventory_result: InventoryResult,
) -> None:
    serialized = prepare_inventory_result(inventory_result, max_result_bytes=10_000)

    with pytest.raises(AnalysisResultSerializationError) as raised:
        prepare_inventory_result(
            inventory_result,
            max_result_bytes=len(serialized.json_bytes) - 1,
        )

    assert raised.value.code is AnalysisResultErrorCode.RESULT_TOO_LARGE


def test_deterministic_json_rejects_non_string_dictionary_keys() -> None:
    payload = cast(dict[str, object], {1: "unsafe"})

    with pytest.raises(AnalysisResultSerializationError) as raised:
        deterministic_json_bytes(payload)

    assert raised.value.code is AnalysisResultErrorCode.RESULT_SERIALIZATION_FAILED
