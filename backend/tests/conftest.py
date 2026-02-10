"""Pytest configuration and fixtures."""

import pytest


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Test database URL."""
    return "postgresql+asyncpg://postgres:postgres@localhost:5432/price_radar_test"
