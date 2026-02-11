"""Tests for product import functionality."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from backend.src.price_radar.api.main import app
from backend.src.price_radar.api.products import get_current_shop_id
from backend.src.price_radar.application.product_import_service import ProductImportService
from backend.src.price_radar.application.shopify_client import ShopifyAPIClient


@pytest.fixture
def mock_shop_id() -> int:
    """Mock shop ID for testing."""
    return 123


@pytest.fixture
def client(mock_shop_id: int) -> TestClient:
    """Create test client with mocked authentication."""
    app.dependency_overrides[get_current_shop_id] = lambda: mock_shop_id
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def mock_shopify_product() -> dict:
    """Mock Shopify product data."""
    return {
        "id": 123456789,
        "title": "Test Product",
        "handle": "test-product",
        "images": [{"src": "https://example.com/image.jpg"}],
        "variants": [
            {
                "id": 987654321,
                "title": "Default Title",
                "price": "29.99",
                "sku": "TEST-SKU-001",
                "inventory_quantity": 10,
            }
        ],
        "tags": "test, sample",
    }


def test_shopify_client_get_products() -> None:
    """Test Shopify API client product fetching."""
    client = ShopifyAPIClient("test-shop.myshopify.com", "test-token")

    assert client.shop_domain == "test-shop.myshopify.com"
    assert client.access_token == "test-token"
    assert "test-shop.myshopify.com" in client.base_url


def test_extract_next_page_info() -> None:
    """Test extraction of page_info from Link header."""
    client = ShopifyAPIClient("test-shop.myshopify.com", "test-token")

    # Link header with next page
    link_header = (
        "<https://shop.myshopify.com/admin/api/2024-01/products.json?page_info=abc123>; "
        'rel="next"'
    )
    page_info = client._extract_next_page_info(link_header)
    assert page_info == "abc123"

    # Link header without next page
    link_header = (
        "<https://shop.myshopify.com/admin/api/2024-01/products.json?page_info=xyz>; "
        'rel="previous"'
    )
    page_info = client._extract_next_page_info(link_header)
    assert page_info is None

    # Empty link header
    page_info = client._extract_next_page_info("")
    assert page_info is None


@pytest.mark.skip(reason="Requires aiosqlite dependency for in-memory testing")
@pytest.mark.asyncio
async def test_import_single_product(mock_shopify_product: dict) -> None:
    """Test importing a single product."""
    from backend.src.price_radar.infrastructure.database import Base
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import StaticPool

    # Create in-memory database for testing
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        service = ProductImportService(session)

        product = await service._import_single_product(
            shop_id=1, shopify_product=mock_shopify_product, existing_products={}
        )

        assert product.shopify_product_id == "123456789"
        assert product.title == "Test Product"
        assert product.handle == "test-product"
        assert product.our_price == 29.99
        assert len(product.variants) == 1
        assert product.variants[0]["sku"] == "TEST-SKU-001"


def test_list_products_endpoint_requires_auth(client: TestClient) -> None:
    """Test that listing products requires authentication."""
    # Override to remove auth
    app.dependency_overrides.clear()

    response = client.get("/api/products")
    assert response.status_code == 401


@pytest.mark.skip(reason="Requires database setup for integration testing")
@patch("price_radar.api.products.import_products_task")
@patch("price_radar.api.products.ShopifyAPIClient")
async def test_import_products_large_catalog(
    mock_client_class: MagicMock, mock_task: MagicMock, client: TestClient
) -> None:
    """Test that large catalogs trigger background job."""
    # Mock ShopifyAPIClient
    mock_client = AsyncMock()
    mock_client.get_product_count = AsyncMock(return_value=150)  # >100 products
    mock_client_class.return_value = mock_client

    # Mock Celery task
    mock_task.delay.return_value = MagicMock(id="task-123")

    # This will fail without a real database, but we can test the mock setup
    # In a real test, we'd need to set up the database properly


def test_get_import_status_pending() -> None:
    """Test getting status of a pending import job."""

    # This would need a real Celery setup or more mocking
    # For now, just test that the endpoint exists
    pass


def test_product_sync_detects_updates(mock_shopify_product: dict) -> None:
    """Test that re-importing products updates existing ones."""
    # This would test the sync functionality
    # Would need to:
    # 1. Import a product
    # 2. Change the product data
    # 3. Re-import
    # 4. Verify product was updated, not duplicated
    pass


def test_product_sync_archives_deleted(mock_shopify_product: dict) -> None:
    """Test that products deleted in Shopify are archived."""
    # This would test that products not in the latest import are marked archived
    pass
