"""API tests for lifecycle-aware persisted analysis results."""

import asyncio
from datetime import UTC, datetime
from typing import NoReturn, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from repolens_api import api
from repolens_api.analysis_results import (
    AnalysisOutput,
    QualityAnalysisOutput,
    serialize_inventory_result,
)
from repolens_api.inventory.contracts import InventoryResult
from repolens_api.main import app
from repolens_api.models import Analysis, AnalysisResult, AnalysisStatus, Repository

REQUESTED_AT = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
STARTED_AT = datetime(2026, 7, 23, 10, 1, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 7, 23, 10, 2, tzinfo=UTC)


async def _create_analysis(
    sessions: async_sessionmaker[AsyncSession],
    *,
    status: AnalysisStatus,
    payload: dict[str, object] | None = None,
    schema_version: int = 1,
    error_code: str | None = None,
) -> UUID:
    async with sessions() as session:
        repository = Repository(
            canonical_url=f"https://github.com/example/result-{uuid4()}",
            owner="example",
            name="result-repository",
        )
        analysis = Analysis(
            repository=repository,
            status=status,
            requested_at=REQUESTED_AT,
            started_at=STARTED_AT if status is not AnalysisStatus.QUEUED else None,
            completed_at=(
                COMPLETED_AT
                if status in {AnalysisStatus.COMPLETED, AnalysisStatus.FAILED}
                else None
            ),
            error_code=error_code,
            error_message="Safe persisted failure." if status is AnalysisStatus.FAILED else None,
            processing_token="internal-processing-token",
        )
        session.add(analysis)
        await session.flush()
        if payload is not None:
            session.add(
                AnalysisResult(
                    analysis_id=analysis.id,
                    schema_version=schema_version,
                    payload=payload,
                )
            )
        await session.commit()
        return analysis.id


def test_result_endpoint_returns_analysis_not_found(api_client: TestClient) -> None:
    response = api_client.get(f"/api/v1/analyses/{uuid4()}/result")

    assert response.status_code == 404
    assert response.json()["type"] == "analysis_not_found"


@pytest.mark.parametrize(
    "status",
    [AnalysisStatus.QUEUED, AnalysisStatus.PROCESSING],
)
def test_result_endpoint_returns_not_ready_for_non_terminal_analysis(
    api_client: TestClient,
    test_sessions: async_sessionmaker[AsyncSession],
    status: AnalysisStatus,
) -> None:
    analysis_id = asyncio.run(_create_analysis(test_sessions, status=status))

    response = api_client.get(f"/api/v1/analyses/{analysis_id}/result")

    assert response.status_code == 409
    assert response.json() == {
        "type": "analysis_not_ready",
        "title": "Analysis result not ready",
        "status": 409,
        "detail": "The analysis result is not ready.",
    }


def test_result_endpoint_returns_safe_failed_problem_code(
    api_client: TestClient,
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    analysis_id = asyncio.run(
        _create_analysis(
            test_sessions,
            status=AnalysisStatus.FAILED,
            error_code="repository_unavailable",
        )
    )

    response = api_client.get(f"/api/v1/analyses/{analysis_id}/result")

    assert response.status_code == 409
    assert response.json()["type"] == "analysis_failed"
    assert response.json()["error_code"] == "repository_unavailable"
    assert "Safe persisted failure" not in response.text
    assert "internal-processing-token" not in response.text


def test_result_endpoint_omits_null_failure_code(
    api_client: TestClient,
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    analysis_id = asyncio.run(_create_analysis(test_sessions, status=AnalysisStatus.FAILED))

    response = api_client.get(f"/api/v1/analyses/{analysis_id}/result")

    assert response.status_code == 409
    assert "error_code" not in response.json()


def test_completed_analysis_without_result_is_integrity_error(
    api_client: TestClient,
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    analysis_id = asyncio.run(_create_analysis(test_sessions, status=AnalysisStatus.COMPLETED))

    response = api_client.get(f"/api/v1/analyses/{analysis_id}/result")

    assert response.status_code == 500
    assert response.json()["type"] == "analysis_result_missing"


def test_completed_analysis_returns_typed_result(
    api_client: TestClient,
    test_sessions: async_sessionmaker[AsyncSession],
    inventory_result: InventoryResult,
) -> None:
    analysis_id = asyncio.run(
        _create_analysis(
            test_sessions,
            status=AnalysisStatus.COMPLETED,
            payload=serialize_inventory_result(inventory_result),
        )
    )

    response = api_client.get(f"/api/v1/analyses/{analysis_id}/result")

    assert response.status_code == 200
    body = response.json()
    assert body["analysis_id"] == str(analysis_id)
    assert body["result_schema_version"] == 1
    assert body["repository"] == {
        "id": body["repository"]["id"],
        "canonical_url": body["repository"]["canonical_url"],
        "owner": "example",
        "name": "result-repository",
        "default_branch": None,
    }
    assert body["repository_summary"]["regular_file_count"] == 3
    assert body["languages"][0]["name"] == "Python"
    assert body["important_files"][0]["kind"] == "readme"
    assert body["technologies"][0]["name"] == "FastAPI"
    assert body["entry_points"][0]["relative_path"] == "src/main.py"
    assert body["warnings"][0]["code"] == "file_unreadable"
    assert body["code_structure"] is None
    assert body["quality_findings"] is None
    assert body["requested_at"] == "2026-07-23T10:00:00Z"
    assert body["started_at"] == "2026-07-23T10:01:00Z"
    assert body["completed_at"] == "2026-07-23T10:02:00Z"
    serialized = response.text
    for forbidden in (
        "internal-processing-token",
        "/tmp/repolens-workspaces",
        r"C:\private",
        "PRIVATE_SOURCE_BODY",
    ):
        assert forbidden not in serialized


def test_unsupported_result_schema_returns_safe_error(
    api_client: TestClient,
    test_sessions: async_sessionmaker[AsyncSession],
    inventory_result: InventoryResult,
) -> None:
    analysis_id = asyncio.run(
        _create_analysis(
            test_sessions,
            status=AnalysisStatus.COMPLETED,
            payload=serialize_inventory_result(inventory_result),
            schema_version=99,
        )
    )

    response = api_client.get(f"/api/v1/analyses/{analysis_id}/result")

    assert response.status_code == 500
    assert response.json()["type"] == "unsupported_result_schema"


def test_completed_analysis_returns_typed_version_two_structure(
    api_client: TestClient,
    test_sessions: async_sessionmaker[AsyncSession],
    analysis_output: AnalysisOutput,
) -> None:
    analysis_id = asyncio.run(
        _create_analysis(
            test_sessions,
            status=AnalysisStatus.COMPLETED,
            payload=serialize_inventory_result(analysis_output),
            schema_version=2,
        )
    )

    response = api_client.get(f"/api/v1/analyses/{analysis_id}/result")

    assert response.status_code == 200
    body = response.json()
    assert body["result_schema_version"] == 2
    assert body["code_structure"]["summary"]["total_symbol_count"] == 1
    assert body["code_structure"]["files"][0]["relative_path"] == "src/main.py"
    assert body["code_structure"]["symbols"][0]["name"] == "create_app"
    assert body["code_structure"]["imports"][0]["module"] == "fastapi"
    assert body["code_structure"]["warnings"][0]["code"] == "source_syntax_error"
    assert body["quality_findings"] is None
    assert "PRIVATE_SOURCE_BODY" not in response.text
    assert "/tmp/repolens-workspaces" not in response.text


def test_version_two_payload_requires_code_structure(
    api_client: TestClient,
    test_sessions: async_sessionmaker[AsyncSession],
    inventory_result: InventoryResult,
) -> None:
    analysis_id = asyncio.run(
        _create_analysis(
            test_sessions,
            status=AnalysisStatus.COMPLETED,
            payload=serialize_inventory_result(inventory_result),
            schema_version=2,
        )
    )

    response = api_client.get(f"/api/v1/analyses/{analysis_id}/result")

    assert response.status_code == 500
    assert response.json()["type"] == "analysis_result_invalid"


def test_completed_analysis_returns_typed_version_three_quality_findings(
    api_client: TestClient,
    test_sessions: async_sessionmaker[AsyncSession],
    quality_analysis_output: QualityAnalysisOutput,
) -> None:
    analysis_id = asyncio.run(
        _create_analysis(
            test_sessions,
            status=AnalysisStatus.COMPLETED,
            payload=serialize_inventory_result(quality_analysis_output),
            schema_version=3,
        )
    )

    response = api_client.get(f"/api/v1/analyses/{analysis_id}/result")

    assert response.status_code == 200
    body = response.json()
    assert body["result_schema_version"] == 3
    assert body["code_structure"]["summary"]["total_symbol_count"] == 1
    quality = body["quality_findings"]
    assert quality["summary"]["total_finding_count"] == 1
    assert quality["findings"][0]["code"] == "documentation_present"
    assert quality["findings"][0]["related_paths"] == ["README.md"]
    assert "PRIVATE_SOURCE_BODY" not in response.text
    assert "processing-token" not in response.text


def test_version_three_payload_requires_quality_findings(
    api_client: TestClient,
    test_sessions: async_sessionmaker[AsyncSession],
    analysis_output: AnalysisOutput,
) -> None:
    analysis_id = asyncio.run(
        _create_analysis(
            test_sessions,
            status=AnalysisStatus.COMPLETED,
            payload=serialize_inventory_result(analysis_output),
            schema_version=3,
        )
    )

    response = api_client.get(f"/api/v1/analyses/{analysis_id}/result")

    assert response.status_code == 500
    assert response.json()["type"] == "analysis_result_invalid"


def test_version_three_payload_rejects_non_contract_quality_text(
    api_client: TestClient,
    test_sessions: async_sessionmaker[AsyncSession],
    quality_analysis_output: QualityAnalysisOutput,
) -> None:
    payload = serialize_inventory_result(quality_analysis_output)
    quality = cast(dict[str, object], payload["quality_findings"])
    findings = cast(list[dict[str, object]], quality["findings"])
    findings[0]["message"] = "PRIVATE README paragraph"
    analysis_id = asyncio.run(
        _create_analysis(
            test_sessions,
            status=AnalysisStatus.COMPLETED,
            payload=payload,
            schema_version=3,
        )
    )

    response = api_client.get(f"/api/v1/analyses/{analysis_id}/result")

    assert response.status_code == 500
    assert response.json()["type"] == "analysis_result_invalid"
    assert "PRIVATE" not in response.text


def test_version_three_payload_rejects_inconsistent_quality_summary(
    api_client: TestClient,
    test_sessions: async_sessionmaker[AsyncSession],
    quality_analysis_output: QualityAnalysisOutput,
) -> None:
    payload = serialize_inventory_result(quality_analysis_output)
    quality = cast(dict[str, object], payload["quality_findings"])
    summary = cast(dict[str, object], quality["summary"])
    summary["positive_signal_count"] = 99
    analysis_id = asyncio.run(
        _create_analysis(
            test_sessions,
            status=AnalysisStatus.COMPLETED,
            payload=payload,
            schema_version=3,
        )
    )

    response = api_client.get(f"/api/v1/analyses/{analysis_id}/result")

    assert response.status_code == 500
    assert response.json()["type"] == "analysis_result_invalid"


def test_version_two_payload_rejects_parser_diagnostic_message(
    api_client: TestClient,
    test_sessions: async_sessionmaker[AsyncSession],
    analysis_output: AnalysisOutput,
) -> None:
    payload = serialize_inventory_result(analysis_output)
    structure = cast(dict[str, object], payload["code_structure"])
    warnings = cast(list[dict[str, object]], structure["warnings"])
    warnings[0]["message"] = "PRIVATE parser exception and source line"
    analysis_id = asyncio.run(
        _create_analysis(
            test_sessions,
            status=AnalysisStatus.COMPLETED,
            payload=payload,
            schema_version=2,
        )
    )

    response = api_client.get(f"/api/v1/analyses/{analysis_id}/result")

    assert response.status_code == 500
    assert response.json()["type"] == "analysis_result_invalid"
    assert "PRIVATE" not in response.text


@pytest.mark.parametrize(
    "payload",
    [
        {"languages": []},
        {
            "repository_summary": {},
            "languages": [],
            "important_files": [],
            "technologies": [],
            "entry_points": [],
            "warnings": [],
            "unexpected_private_field": "PRIVATE_SOURCE_BODY",
        },
    ],
)
def test_invalid_result_payload_returns_safe_error(
    api_client: TestClient,
    test_sessions: async_sessionmaker[AsyncSession],
    payload: dict[str, object],
) -> None:
    analysis_id = asyncio.run(
        _create_analysis(
            test_sessions,
            status=AnalysisStatus.COMPLETED,
            payload=payload,
        )
    )

    response = api_client.get(f"/api/v1/analyses/{analysis_id}/result")

    assert response.status_code == 500
    assert response.json()["type"] == "analysis_result_invalid"
    assert "PRIVATE_SOURCE_BODY" not in response.text
    assert "validation error" not in response.text.casefold()


def test_result_database_failure_is_sanitized(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_load(*_args: object, **_kwargs: object) -> NoReturn:
        raise SQLAlchemyError("private database host and password")

    monkeypatch.setattr(api, "get_analysis_record", fail_load)

    response = api_client.get(f"/api/v1/analyses/{uuid4()}/result")

    assert response.status_code == 503
    assert response.json()["type"] == "database_error"
    assert "private database" not in response.text


def test_openapi_documents_typed_result_and_problem_responses() -> None:
    operation = app.openapi()["paths"]["/api/v1/analyses/{analysis_id}/result"]["get"]
    success_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]

    assert success_schema["$ref"].endswith("/AnalysisResultResponse")
    for status_code in ("404", "409", "422", "500", "503"):
        content = operation["responses"][status_code]["content"]
        assert set(content) == {"application/problem+json"}
        assert content["application/problem+json"]["schema"]["title"] == "ProblemDetail"

    properties = app.openapi()["components"]["schemas"]["AnalysisResultResponse"]["properties"]
    assert "processing_token" not in properties
    assert set(properties) == {
        "analysis_id",
        "result_schema_version",
        "repository",
        "repository_summary",
        "languages",
        "important_files",
        "technologies",
        "entry_points",
        "warnings",
        "code_structure",
        "quality_findings",
        "requested_at",
        "started_at",
        "completed_at",
    }
