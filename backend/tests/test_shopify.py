"""Tests for Shopify integration."""

import pytest
from fastapi.testclient import TestClient
from price_radar.api.main import app


@pytest.fixture
def client() -> TestClient:
    """Create test client."""
    return TestClient(app)


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
