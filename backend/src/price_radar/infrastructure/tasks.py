"""Celery tasks."""

from price_radar.infrastructure.celery_app import celery_app


@celery_app.task  # type: ignore[untyped-decorator]
def example_task() -> str:
    """Example Celery task."""
    return "Task completed"
