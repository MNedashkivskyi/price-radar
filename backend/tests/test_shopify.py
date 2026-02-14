"""Tests for Shopify integration."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from price_radar.api.main import app
from price_radar.api.shopify import get_shopify_service
from price_radar.application.shopify_service import ShopifyService


@pytest.fixture
def mock_shopify_service() -> ShopifyService:
    """Create mock Shopify service."""
    service = MagicMock(spec=ShopifyService)
    service.generate_install_url = MagicMock(
        return_value="https://test-shop.myshopify.com/admin/oauth/authorize?client_id=test&scope=read_products&redirect_uri=http://localhost:8000/api/shopify/callback"
    )
    service.get_store = AsyncMock(return_value=None)
    return service


@pytest.fixture
def client(mock_shopify_service: ShopifyService) -> TestClient:
    """Create test client with mocked dependencies."""
    app.dependency_overrides[get_shopify_service] = lambda: mock_shopify_service
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_install_endpoint_redirects(client: TestClient) -> None:
    """Test that install endpoint redirects to Shopify."""
    response = client.get("/api/shopify/install?shop=test-shop", follow_redirects=False)
    assert response.status_code == 307
    assert "test-shop.myshopify.com" in response.headers["location"]
    assert "oauth/authorize" in response.headers["location"]


def test_install_endpoint_normalizes_shop_domain(client: TestClient) -> None:
    """Test that shop domain is normalized."""
    response = client.get(
        "/api/shopify/install?shop=test-shop.myshopify.com", follow_redirects=False
    )
    assert response.status_code == 307
    assert "test-shop.myshopify.com" in response.headers["location"]


def test_get_store_not_found(client: TestClient) -> None:
    """Test getting non-existent store returns 404."""
    response = client.get("/api/shopify/stores/nonexistent.myshopify.com")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
