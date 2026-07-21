"""Tests for Celery task registration."""

from repolens_api.celery_app import celery_app


def test_mock_analysis_task_is_registered() -> None:
    assert "repolens.process_mock_analysis" in celery_app.tasks
