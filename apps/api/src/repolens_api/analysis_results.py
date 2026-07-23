"""Explicit deterministic serialization for safe inventory results."""

import json
import math
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath

from repolens_api.code_structure.contracts import (
    SOURCE_STRUCTURE_WARNING_MESSAGES,
    CodeStructureResult,
    SourceStructureWarningCode,
)
from repolens_api.inventory.contracts import InventoryResult

ANALYSIS_RESULT_SCHEMA_VERSION = 2
LEGACY_INVENTORY_SCHEMA_VERSION = 1
SUPPORTED_RESULT_SCHEMA_VERSIONS = frozenset(
    {LEGACY_INVENTORY_SCHEMA_VERSION, ANALYSIS_RESULT_SCHEMA_VERSION}
)


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


@dataclass(frozen=True, slots=True)
class AnalysisOutput:
    """Current worker output combining inventory and source structure."""

    schema_version: int
    inventory: InventoryResult
    code_structure: CodeStructureResult


type PersistableAnalysisResult = InventoryResult | AnalysisOutput


def serialize_inventory_result(result: PersistableAnalysisResult) -> dict[str, object]:
    """Convert an inventory result to an explicit JSON-compatible payload."""
    try:
        if (
            isinstance(result, AnalysisOutput)
            and result.schema_version != ANALYSIS_RESULT_SCHEMA_VERSION
        ) or (
            isinstance(result, InventoryResult)
            and result.schema_version != LEGACY_INVENTORY_SCHEMA_VERSION
        ):
            raise AnalysisResultSerializationError(
                AnalysisResultErrorCode.RESULT_SERIALIZATION_FAILED
            )
        inventory = result.inventory if isinstance(result, AnalysisOutput) else result
        payload: dict[str, object] = {
            "repository_summary": {
                "regular_file_count": inventory.repository_summary.regular_file_count,
                "analyzed_directory_count": inventory.repository_summary.analyzed_directory_count,
                "total_file_bytes": inventory.repository_summary.total_file_bytes,
                "max_directory_depth": inventory.repository_summary.max_directory_depth,
                "top_level_directories": [
                    _relative_path(path)
                    for path in inventory.repository_summary.top_level_directories
                ],
                "directories_by_file_count": [
                    {
                        "relative_path": _relative_path(item.relative_path),
                        "file_count": item.file_count,
                    }
                    for item in inventory.repository_summary.directories_by_file_count
                ],
                "ignored_directory_count": inventory.repository_summary.ignored_directory_count,
                "binary_file_count": inventory.repository_summary.binary_file_count,
                "unreadable_file_count": inventory.repository_summary.unreadable_file_count,
                "skipped_content_file_count": (
                    inventory.repository_summary.skipped_content_file_count
                ),
                "sensitive_file_count": inventory.repository_summary.sensitive_file_count,
            },
            "languages": [
                {
                    "name": item.name,
                    "file_count": item.file_count,
                    "total_bytes": item.total_bytes,
                    "percentage": item.percentage,
                }
                for item in inventory.languages
            ],
            "important_files": [
                {
                    "kind": item.kind,
                    "count": item.count,
                    "paths": [_relative_path(path) for path in item.paths],
                    "truncated": item.truncated,
                }
                for item in inventory.important_files
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
                for item in inventory.technologies
            ],
            "entry_points": [
                {
                    "kind": item.kind,
                    "relative_path": _relative_path(item.relative_path),
                    "confidence": item.confidence.value,
                    "evidence_type": item.evidence_type,
                }
                for item in inventory.entry_points
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
                for item in inventory.warnings
            ],
        }
        if isinstance(result, AnalysisOutput):
            payload["code_structure"] = _serialize_code_structure(result.code_structure)
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
    result: PersistableAnalysisResult,
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


def _serialize_code_structure(result: CodeStructureResult) -> dict[str, object]:
    return {
        "summary": {
            "supported_source_file_count": result.summary.supported_source_file_count,
            "parsed_file_count": result.summary.parsed_file_count,
            "skipped_file_count": result.summary.skipped_file_count,
            "parse_error_file_count": result.summary.parse_error_file_count,
            "total_symbol_count": result.summary.total_symbol_count,
            "total_function_count": result.summary.total_function_count,
            "total_class_count": result.summary.total_class_count,
            "total_method_count": result.summary.total_method_count,
            "total_import_count": result.summary.total_import_count,
            "language_file_counts": [
                {
                    "language": _safe_text(item.language),
                    "file_count": item.file_count,
                }
                for item in result.summary.language_file_counts
            ],
        },
        "files": [
            {
                "relative_path": _relative_path(item.relative_path),
                "language": _safe_text(item.language),
                "category": item.category.value,
                "line_count": item.line_count,
                "symbol_count": item.symbol_count,
                "import_count": item.import_count,
                "class_count": item.class_count,
                "function_count": item.function_count,
                "method_count": item.method_count,
                "parse_status": item.parse_status.value,
                "has_syntax_errors": item.has_syntax_errors,
            }
            for item in result.files
        ],
        "symbols": [
            {
                "relative_path": _relative_path(item.relative_path),
                "language": _safe_text(item.language),
                "kind": item.kind.value,
                "name": _safe_text(item.name),
                "qualified_name": _safe_text(item.qualified_name, maximum=1_024),
                "start_line": item.start_line,
                "end_line": item.end_line,
                "parent_name": (
                    _safe_text(item.parent_name) if item.parent_name is not None else None
                ),
                "parameter_count": item.parameter_count,
                "is_exported": item.is_exported,
                "is_public": item.is_public,
            }
            for item in result.symbols
        ],
        "imports": [
            {
                "relative_path": _relative_path(item.relative_path),
                "language": _safe_text(item.language),
                "module": _safe_text(item.module, maximum=512),
                "imported_names": [_safe_text(name) for name in item.imported_names],
                "import_kind": item.import_kind.value,
                "is_relative": item.is_relative,
                "start_line": item.start_line,
            }
            for item in result.imports
        ],
        "warnings": [
            {
                "code": item.code.value,
                "relative_path": (
                    _relative_path(item.relative_path) if item.relative_path is not None else None
                ),
                "message": _safe_warning_message(item.code, item.message),
            }
            for item in result.warnings
        ],
    }


def _safe_warning_message(code: SourceStructureWarningCode, message: str) -> str:
    if SOURCE_STRUCTURE_WARNING_MESSAGES.get(code) != message:
        raise AnalysisResultSerializationError(AnalysisResultErrorCode.RESULT_SERIALIZATION_FAILED)
    return _safe_text(message)


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


def _safe_text(value: str, *, maximum: int = 255) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise AnalysisResultSerializationError(AnalysisResultErrorCode.RESULT_SERIALIZATION_FAILED)
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise AnalysisResultSerializationError(
            AnalysisResultErrorCode.RESULT_SERIALIZATION_FAILED
        ) from None
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
