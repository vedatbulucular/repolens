"""Tests for the analysis lifecycle API."""

import asyncio
from typing import NoReturn
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from repolens_api import api
from repolens_api.api import get_analysis_dispatcher
from repolens_api.main import app
from repolens_api.models import Analysis, AnalysisStatus, Repository


def test_create_analysis_returns_queued_record(
    api_client: TestClient,
    dispatched_analysis_ids: list[UUID],
) -> None:
    response = api_client.post(
        "/api/v1/analyses",
        json={"repository_url": "https://github.com/openai/openai-python.git"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["repository"]["canonical_url"] == ("https://github.com/openai/openai-python")
    assert body["repository"]["owner"] == "openai"
    assert body["repository"]["name"] == "openai-python"
    assert body["requested_at"].endswith("Z")
    assert dispatched_analysis_ids == [UUID(body["id"])]


async def _repository_and_analysis_counts(
    sessions: async_sessionmaker[AsyncSession],
) -> tuple[int, int]:
    async with sessions() as session:
        repository_count = await session.scalar(select(func.count()).select_from(Repository))
        analysis_count = await session.scalar(select(func.count()).select_from(Analysis))
        return int(repository_count or 0), int(analysis_count or 0)


def test_create_analysis_reuses_canonical_repository(
    api_client: TestClient,
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    first = api_client.post(
        "/api/v1/analyses",
        json={"repository_url": "https://github.com/openai/openai-python/"},
    )
    second = api_client.post(
        "/api/v1/analyses",
        json={"repository_url": "https://github.com/openai/openai-python.git"},
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["repository"]["id"] == second.json()["repository"]["id"]
    assert asyncio.run(_repository_and_analysis_counts(test_sessions)) == (1, 2)


def test_create_analysis_rejects_unsupported_url(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/v1/analyses",
        json={"repository_url": "http://localhost/owner/repository"},
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "invalid_repository_url",
        "title": "Invalid repository URL",
        "status": 422,
        "detail": "Only public HTTPS GitHub repository URLs are supported.",
    }


def test_get_analysis_returns_created_record(api_client: TestClient) -> None:
    created = api_client.post(
        "/api/v1/analyses",
        json={"repository_url": "https://github.com/openai/openai-python"},
    )

    response = api_client.get(f"/api/v1/analyses/{created.json()['id']}")

    assert response.status_code == 200
    assert response.json() == created.json()


def test_get_analysis_returns_machine_readable_not_found(api_client: TestClient) -> None:
    response = api_client.get(f"/api/v1/analyses/{uuid4()}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == "analysis_not_found"
    assert "Traceback" not in response.text


def test_queue_failure_returns_safe_error_and_marks_analysis_failed(
    api_client: TestClient,
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    def fail_dispatch(_analysis_id: UUID) -> NoReturn:
        raise RuntimeError("redis password and internal host")

    app.dependency_overrides[get_analysis_dispatcher] = lambda: fail_dispatch

    response = api_client.post(
        "/api/v1/analyses",
        json={"repository_url": "https://github.com/openai/openai-python"},
    )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == "analysis_queue_unavailable"
    assert "redis password" not in response.text

    async def load_only_analysis() -> Analysis:
        async with test_sessions() as session:
            analysis = await session.scalar(select(Analysis))
            assert analysis is not None
            return analysis

    persisted = asyncio.run(load_only_analysis())
    assert persisted.status is AnalysisStatus.FAILED
    assert persisted.started_at is None
    assert persisted.completed_at is not None
    assert persisted.error_message == "Analysis queue dispatch failed."


def test_database_failure_returns_safe_error(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_create(*_args: object, **_kwargs: object) -> NoReturn:
        raise SQLAlchemyError("database password and internal host")

    monkeypatch.setattr(api, "create_analysis_record", fail_create)

    response = api_client.post(
        "/api/v1/analyses",
        json={"repository_url": "https://github.com/openai/openai-python"},
    )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == "database_error"
    assert "database password" not in response.text


def test_request_validation_uses_problem_details(api_client: TestClient) -> None:
    response = api_client.post("/api/v1/analyses", json={})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == "invalid_request"


def test_invalid_analysis_uuid_uses_problem_details(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/analyses/not-a-uuid")

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "invalid_request",
        "title": "Invalid request",
        "status": 422,
        "detail": "The request body or path parameters are invalid.",
    }


def test_openapi_documents_problem_response_media_types() -> None:
    paths = app.openapi()["paths"]
    expected_responses = {
        ("/api/v1/analyses", "post"): {"422", "503"},
        ("/api/v1/analyses/{analysis_id}", "get"): {"404", "422", "503"},
    }

    for (path, method), status_codes in expected_responses.items():
        responses = paths[path][method]["responses"]
        for status_code in status_codes:
            content = responses[status_code]["content"]
            assert set(content) == {"application/problem+json"}
            assert content["application/problem+json"]["schema"]["title"] == ("ProblemDetail")
