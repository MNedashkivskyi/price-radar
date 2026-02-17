"""Celery application configuration."""

from celery import Celery  # type: ignore[import-untyped]
from celery.schedules import crontab  # type: ignore[import-untyped]

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
    # Auto-discover tasks from the tasks module
    imports=["price_radar.infrastructure.tasks"],
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=10,
    broker_connection_timeout=30,
    beat_schedule_filename="/tmp/celerybeat-schedule",
)

# Celery Beat schedule
celery_app.conf.beat_schedule = {
    "example-periodic-task": {
        "task": "price_radar.infrastructure.tasks.example_task",
        "schedule": crontab(minute="*/5"),
    },
    # ── Price scraping schedules ─────────────────────────────────────
    # Free plan: scrape every 6 hours (4x/day)
    "scrape-prices-free": {
        "task": "price_radar.infrastructure.tasks.scrape_all_active",
        "schedule": crontab(minute="0", hour="*/6"),
        "kwargs": {"plan": "free"},
    },
    # Basic plan: scrape every 3 hours (8x/day)
    "scrape-prices-basic": {
        "task": "price_radar.infrastructure.tasks.scrape_all_active",
        "schedule": crontab(minute="0", hour="*/3"),
        "kwargs": {"plan": "basic"},
    },
    # Pro plan: scrape every hour (24x/day)
    "scrape-prices-pro": {
        "task": "price_radar.infrastructure.tasks.scrape_all_active",
        "schedule": crontab(minute="0", hour="*"),
        "kwargs": {"plan": "pro"},
    },
    # Enterprise plan: scrape every 30 minutes (48x/day)
    "scrape-prices-enterprise": {
        "task": "price_radar.infrastructure.tasks.scrape_all_active",
        "schedule": crontab(minute="*/30"),
        "kwargs": {"plan": "enterprise"},
    },
    # ── Circuit breaker probe ─────────────────────────────────────────
    # Probe OPEN (broken) domains every hour to check if they recovered
    "probe-broken-domains": {
        "task": "price_radar.infrastructure.tasks.probe_broken_domains",
        "schedule": crontab(minute="15", hour="*"),  # :15 past each hour
    },
}

# Import tasks to ensure they are registered
# This must be at the end to avoid circular imports
from price_radar.infrastructure import tasks  # noqa: E402, F401
