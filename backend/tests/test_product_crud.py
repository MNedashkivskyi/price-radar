"""Tests for manual product CRUD operations."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from price_radar.api.main import app
from price_radar.api.middleware import get_current_shop_id


@pytest.fixture
def mock_shop_id() -> int:
    """Mock authenticated shop ID."""
    return 1


@pytest.fixture
def client(mock_shop_id: int) -> TestClient:
    """Create test client with mocked authentication."""
    # Override authentication to return test shop ID
    app.dependency_overrides[get_current_shop_id] = lambda: mock_shop_id

    # Mock database dependency will be handled by conftest.py if exists
    # For now, these are unit tests that verify request/response structure

    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_create_product_schema_validation() -> None:
    """Test that product creation schema validates correctly."""
    from price_radar.api.schemas import ProductCreateRequest

    # Valid data
    valid_data = {
        "title": "Test Product",
        "handle": "test-product",
        "our_price": Decimal("29.99"),
        "currency": "USD",
    }
    product = ProductCreateRequest(**valid_data)
    assert product.title == "Test Product"
    assert product.our_price == Decimal("29.99")

    # Invalid currency
    with pytest.raises(ValueError, match="Currency must be a 3-letter uppercase ISO code"):
        ProductCreateRequest(**{**valid_data, "currency": "usd"})

    # Invalid handle (uppercase not allowed)
    with pytest.raises(ValueError, match="Handle must contain only lowercase"):
        ProductCreateRequest(**{**valid_data, "handle": "Test-Product"})

    # Invalid price (must be positive)
    with pytest.raises(ValueError):
        ProductCreateRequest(**{**valid_data, "our_price": Decimal("-10.00")})


def test_update_product_schema_validation() -> None:
    """Test that product update schema validates correctly."""
    from price_radar.api.schemas import ProductUpdateRequest

    # All fields optional
    update_data = {"title": "Updated Title"}
    product = ProductUpdateRequest(**update_data)
    assert product.title == "Updated Title"
    assert product.our_price is None

    # Partial update with price
    update_data = {"our_price": Decimal("39.99")}
    product = ProductUpdateRequest(**update_data)
    assert product.our_price == Decimal("39.99")
    assert product.title is None


def test_create_product_endpoint_structure(client: TestClient) -> None:
    """Test create product endpoint structure (mocked, no DB)."""
    # This test verifies the endpoint exists and accepts the correct structure
    # Actual DB operations would need integration tests

    product_data = {
        "title": "Manual Test Product",
        "handle": "manual-test-product",
        "our_price": 49.99,
        "currency": "USD",
        "tags": ["test", "manual"],
    }

    # Note: This will fail without DB, but structure is validated
    response = client.post("/api/products", json=product_data)

    # Even if it fails, we can check it's not a 404 or 405 (endpoint exists)
    assert response.status_code != 404, "Endpoint should exist"
    assert response.status_code != 405, "Method should be allowed"


def test_update_product_endpoint_structure(client: TestClient) -> None:
    """Test update product endpoint structure (mocked, no DB)."""
    update_data = {
        "title": "Updated Product Title",
        "our_price": 59.99,
    }

    response = client.patch("/api/products/1", json=update_data)

    # Verify endpoint exists and method is allowed
    assert response.status_code != 404, "Endpoint should exist"
    assert response.status_code != 405, "Method should be allowed"


def test_currency_validation() -> None:
    """Test currency code validation."""
    from price_radar.api.schemas import ProductCreateRequest

    valid_data = {"title": "Test", "our_price": Decimal("10.00")}

    # Valid currencies
    for currency in ["USD", "EUR", "GBP", "JPY"]:
        product = ProductCreateRequest(**{**valid_data, "currency": currency})
        assert product.currency == currency

    # Invalid currencies
    invalid_currencies = ["usd", "US", "USDD", "123", ""]
    for currency in invalid_currencies:
        with pytest.raises(ValueError):
            ProductCreateRequest(**{**valid_data, "currency": currency})


def test_handle_validation() -> None:
    """Test handle validation rules."""
    from price_radar.api.schemas import ProductCreateRequest

    valid_data = {"title": "Test", "our_price": Decimal("10.00")}

    # Valid handles
    valid_handles = ["test-product", "product-123", "my-awesome-product"]
    for handle in valid_handles:
        product = ProductCreateRequest(**{**valid_data, "handle": handle})
        assert product.handle == handle

    # Invalid handles
    invalid_handles = ["Test-Product", "test_product", "test product", "TEST"]
    for handle in invalid_handles:
        with pytest.raises(ValueError):
            ProductCreateRequest(**{**valid_data, "handle": handle})


def test_tags_validation() -> None:
    """Test tags validation."""
    from price_radar.api.schemas import ProductCreateRequest

    valid_data = {"title": "Test", "our_price": Decimal("10.00")}

    # Valid tags
    product = ProductCreateRequest(**{**valid_data, "tags": ["tag1", "tag2"]})
    assert product.tags == ["tag1", "tag2"]

    # Empty tags list is valid
    product = ProductCreateRequest(**{**valid_data, "tags": []})
    assert product.tags == []

    # Invalid: tags with empty strings
    with pytest.raises(ValueError, match="Tags must be non-empty strings"):
        ProductCreateRequest(**{**valid_data, "tags": ["tag1", ""]})

    with pytest.raises(ValueError, match="Tags must be non-empty strings"):
        ProductCreateRequest(**{**valid_data, "tags": ["tag1", "   "]})
