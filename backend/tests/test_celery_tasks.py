"""Tests for Celery task registration and discovery."""

import pytest


def test_celery_app_exists() -> None:
    """Test that Celery app can be imported."""
    from price_radar.infrastructure.celery_app import celery_app

    assert celery_app is not None
    assert celery_app.main == "price_radar"


def test_tasks_are_registered() -> None:
    """Test that tasks are automatically registered with Celery."""
    from price_radar.infrastructure.celery_app import celery_app

    # Get all registered tasks
    registered_tasks = list(celery_app.tasks.keys())

    # Check that our custom tasks are registered
    assert "price_radar.infrastructure.tasks.example_task" in registered_tasks
    assert "price_radar.infrastructure.tasks.import_products_task" in registered_tasks


def test_example_task_callable() -> None:
    """Test that example_task is callable."""
    from price_radar.infrastructure.tasks import example_task

    # Task should be a Celery task object
    assert hasattr(example_task, "delay")
    assert hasattr(example_task, "apply_async")


def test_import_products_task_callable() -> None:
    """Test that import_products_task is callable."""
    from price_radar.infrastructure.tasks import import_products_task

    # Task should be a Celery task object
    assert hasattr(import_products_task, "delay")
    assert hasattr(import_products_task, "apply_async")


def test_celery_config() -> None:
    """Test Celery configuration."""
    from price_radar.infrastructure.celery_app import celery_app

    # Check basic configuration
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.result_serializer == "json"
    assert celery_app.conf.timezone == "UTC"
    assert celery_app.conf.enable_utc is True

    # Check that tasks module is in imports
    assert "price_radar.infrastructure.tasks" in celery_app.conf.imports


def test_beat_schedule_configured() -> None:
    """Test that Celery Beat schedule is configured."""
    from price_radar.infrastructure.celery_app import celery_app

    # Check beat schedule exists
    assert celery_app.conf.beat_schedule is not None
    assert "example-periodic-task" in celery_app.conf.beat_schedule

    # Verify the periodic task configuration
    periodic_task = celery_app.conf.beat_schedule["example-periodic-task"]
    assert periodic_task["task"] == "price_radar.infrastructure.tasks.example_task"
    assert "schedule" in periodic_task
