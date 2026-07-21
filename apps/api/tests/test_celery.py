"""Tests for Celery task registration."""

from repolens_api.celery_app import celery_app


def test_analysis_task_is_registered_with_reliable_delivery_settings() -> None:
    assert "repolens.process_analysis" in celery_app.tasks
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.worker_cancel_long_running_tasks_on_connection_loss is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
