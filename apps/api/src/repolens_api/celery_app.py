"""Celery application configured for analysis lifecycle jobs."""

# Celery does not publish typing metadata, so this import is the narrow boundary
# between the typed application code and Celery's untyped public API.
from celery import Celery  # type: ignore[import-untyped]

from repolens_api.settings import get_settings

settings = get_settings()

celery_app = Celery(
    "repolens",
    broker=settings.redis_url,
    include=["repolens_api.tasks"],
)
celery_app.conf.update(
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    task_ignore_result=True,
    task_serializer="json",
    timezone="UTC",
)
