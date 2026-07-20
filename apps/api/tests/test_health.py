"""Tests for the API health endpoint."""

from fastapi.testclient import TestClient

from repolens_api.main import app

client = TestClient(app)


def test_health_returns_service_status() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "repolens-api",
        "version": "0.1.0",
    }


def test_openapi_metadata_identifies_the_api() -> None:
    assert app.title == "RepoLens API"
    assert app.version == "0.1.0"
