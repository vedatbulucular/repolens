"""Explicit deterministic serialization for safe inventory results."""

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath

from repolens_api.inventory.contracts import InventoryResult

SUPPORTED_RESULT_SCHEMA_VERSIONS = frozenset({1})


class AnalysisResultErrorCode(StrEnum):
    """Safe result preparation failure classifications."""

    RESULT_SERIALIZATION_FAILED = "result_serialization_failed"
    RESULT_TOO_LARGE = "result_too_large"
    RESULT_PERSISTENCE_FAILED = "result_persistence_failed"


class AnalysisResultSerializationError(Exception):
    """Sanitized serialization failure without payload detail."""

    def __init__(self, code: AnalysisResultErrorCode) -> None:
        self.code = code
        self.public_message = (
            "The analysis result exceeds the allowed size."
            if code is AnalysisResultErrorCode.RESULT_TOO_LARGE
            else "The analysis result could not be serialized safely."
        )
        super().__init__(self.public_message)


class AnalysisResultPersistenceError(Exception):
    """Sanitized non-database persistence failure."""

    code = AnalysisResultErrorCode.RESULT_PERSISTENCE_FAILED
    public_message = "The analysis result could not be persisted."

    def __init__(self) -> None:
        super().__init__(self.public_message)


@dataclass(frozen=True, slots=True)
class SerializedInventoryResult:
    """One validated payload and its canonical UTF-8 representation."""

    schema_version: int
    payload: dict[str, object]
    json_bytes: bytes


def serialize_inventory_result(result: InventoryResult) -> dict[str, object]:
    """Convert an inventory result to an explicit JSON-compatible payload."""
    try:
        payload: dict[str, object] = {
            "repository_summary": {
                "regular_file_count": result.repository_summary.regular_file_count,
                "analyzed_directory_count": result.repository_summary.analyzed_directory_count,
                "total_file_bytes": result.repository_summary.total_file_bytes,
                "max_directory_depth": result.repository_summary.max_directory_depth,
                "top_level_directories": [
                    _relative_path(path) for path in result.repository_summary.top_level_directories
                ],
                "directories_by_file_count": [
                    {
                        "relative_path": _relative_path(item.relative_path),
                        "file_count": item.file_count,
                    }
                    for item in result.repository_summary.directories_by_file_count
                ],
                "ignored_directory_count": result.repository_summary.ignored_directory_count,
                "binary_file_count": result.repository_summary.binary_file_count,
                "unreadable_file_count": result.repository_summary.unreadable_file_count,
                "skipped_content_file_count": (
                    result.repository_summary.skipped_content_file_count
                ),
                "sensitive_file_count": result.repository_summary.sensitive_file_count,
            },
            "languages": [
                {
                    "name": item.name,
                    "file_count": item.file_count,
                    "total_bytes": item.total_bytes,
                    "percentage": item.percentage,
                }
                for item in result.languages
            ],
            "important_files": [
                {
                    "kind": item.kind,
                    "count": item.count,
                    "paths": [_relative_path(path) for path in item.paths],
                    "truncated": item.truncated,
                }
                for item in result.important_files
            ],
            "technologies": [
                {
                    "name": item.name,
                    "category": item.category,
                    "confidence": item.confidence.value,
                    "evidence": [
                        {
                            "evidence_type": evidence.evidence_type,
                            "relative_path": _relative_path(evidence.relative_path),
                        }
                        for evidence in item.evidence
                    ],
                    "evidence_truncated": item.evidence_truncated,
                }
                for item in result.technologies
            ],
            "entry_points": [
                {
                    "kind": item.kind,
                    "relative_path": _relative_path(item.relative_path),
                    "confidence": item.confidence.value,
                    "evidence_type": item.evidence_type,
                }
                for item in result.entry_points
            ],
            "warnings": [
                {
                    "code": item.code.value,
                    "relative_path": (
                        _relative_path(item.relative_path)
                        if item.relative_path is not None
                        else None
                    ),
                    "message": item.message,
                }
                for item in result.warnings
            ],
        }
        _validate_json_value(payload)
    except AnalysisResultSerializationError:
        raise
    except (AttributeError, OverflowError, TypeError, ValueError):
        raise AnalysisResultSerializationError(
            AnalysisResultErrorCode.RESULT_SERIALIZATION_FAILED
        ) from None
    return payload


def deterministic_json_bytes(payload: dict[str, object]) -> bytes:
    """Return canonical JSON bytes after rejecting unsupported values."""
    try:
        _validate_json_value(payload)
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return serialized.encode("utf-8", errors="strict")
    except AnalysisResultSerializationError:
        raise
    except (OverflowError, TypeError, UnicodeEncodeError, ValueError):
        raise AnalysisResultSerializationError(
            AnalysisResultErrorCode.RESULT_SERIALIZATION_FAILED
        ) from None


def prepare_inventory_result(
    result: InventoryResult,
    *,
    max_result_bytes: int,
) -> SerializedInventoryResult:
    """Serialize and enforce the all-or-nothing persisted result size limit."""
    if (
        isinstance(result.schema_version, bool)
        or not isinstance(result.schema_version, int)
        or result.schema_version not in SUPPORTED_RESULT_SCHEMA_VERSIONS
        or max_result_bytes <= 0
    ):
        raise AnalysisResultSerializationError(AnalysisResultErrorCode.RESULT_SERIALIZATION_FAILED)
    payload = serialize_inventory_result(result)
    json_bytes = deterministic_json_bytes(payload)
    if len(json_bytes) > max_result_bytes:
        raise AnalysisResultSerializationError(AnalysisResultErrorCode.RESULT_TOO_LARGE)
    return SerializedInventoryResult(
        schema_version=result.schema_version,
        payload=payload,
        json_bytes=json_bytes,
    )


def _relative_path(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise AnalysisResultSerializationError(AnalysisResultErrorCode.RESULT_SERIALIZATION_FAILED)
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in posix_path.parts)
    ):
        raise AnalysisResultSerializationError(AnalysisResultErrorCode.RESULT_SERIALIZATION_FAILED)
    return value


def _validate_json_value(value: object) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AnalysisResultSerializationError(
                AnalysisResultErrorCode.RESULT_SERIALIZATION_FAILED
            )
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise AnalysisResultSerializationError(
                    AnalysisResultErrorCode.RESULT_SERIALIZATION_FAILED
                )
            _validate_json_value(item)
        return
    raise AnalysisResultSerializationError(AnalysisResultErrorCode.RESULT_SERIALIZATION_FAILED)
