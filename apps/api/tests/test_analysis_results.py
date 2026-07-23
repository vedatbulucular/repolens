"""Tests for explicit deterministic inventory result serialization."""

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from repolens_api.analysis_results import (
    AnalysisResultErrorCode,
    AnalysisResultSerializationError,
    deterministic_json_bytes,
    prepare_inventory_result,
    serialize_inventory_result,
)
from repolens_api.inventory.contracts import InventoryResult


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


def test_deterministic_json_bytes_are_equal_for_the_same_logical_result(
    inventory_result: InventoryResult,
) -> None:
    first = prepare_inventory_result(inventory_result, max_result_bytes=10_000)
    second = prepare_inventory_result(inventory_result, max_result_bytes=10_000)

    assert first.payload == second.payload
    assert first.json_bytes == second.json_bytes
    assert first.json_bytes == deterministic_json_bytes(first.payload)


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
