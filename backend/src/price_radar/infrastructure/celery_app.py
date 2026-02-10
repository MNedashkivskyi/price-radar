"""Celery application configuration."""

from celery import Celery
from celery.schedules import crontab

from price_radar.infrastructure.config import settings

celery_app = Celery(
    "price_radar",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# Celery Beat schedule
celery_app.conf.beat_schedule = {
    "example-periodic-task": {
        "task": "price_radar.infrastructure.tasks.example_task",
        "schedule": crontab(minute="*/5"),
    },
}
