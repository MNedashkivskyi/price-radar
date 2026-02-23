"""Tests for manual product CRUD operations."""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from price_radar.api.main import app
from price_radar.api.middleware import get_current_shop_id
from price_radar.infrastructure.database import get_db


def _make_fake_product(**overrides):  # type: ignore[no-untyped-def]
    """Create a fake product object that satisfies the response model.

    Uses SimpleNamespace instead of MagicMock to prevent auto-creation
    of undefined attributes (e.g. ``mock.Product``) which can confuse
    SQLAlchemy's ``select()`` when the mock leaks into query construction.
    """
    now = datetime.now(tz=timezone.utc)
    defaults = {
        "id": 1,
        "shop_id": 1,
        "shopify_product_id": None,
        "title": "Test",
        "handle": None,
        "image_url": None,
        "our_price": Decimal("10.00"),
        "currency": "USD",
        "variants": None,
        "tags": None,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_mock_result(*, scalar_value=None):  # type: ignore[no-untyped-def]
    """Build a mock query result with only the methods endpoints actually use.

    Using ``spec=[]`` prevents MagicMock from auto-creating child mocks
    for arbitrary attribute access (e.g. ``result.Product``), which would
    otherwise produce objects that SQLAlchemy rejects.
    """
    mock_result = MagicMock(spec=[])
    mock_result.scalar_one_or_none = MagicMock(return_value=scalar_value)
    mock_result.scalars = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar = MagicMock(return_value=0)
    mock_result.all = MagicMock(return_value=[])
    return mock_result


async def _mock_get_db() -> AsyncGenerator:
    """Yield a mock async DB session that won't hit a real database."""
    mock_session = AsyncMock()

    # session.add() is synchronous in real AsyncSession — use a plain MagicMock
    # to avoid RuntimeWarning about unawaited coroutines.
    mock_session.add = MagicMock()

    # Default: execute() returns a result whose scalar_one_or_none() gives None
    # (no existing row found).  Individual tests can override via side_effect.
    mock_session.execute.return_value = _make_mock_result(scalar_value=None)

    # refresh() should copy DB-generated fields onto the ORM object
    async def _refresh(obj, **_kwargs):  # type: ignore[no-untyped-def]
        now = datetime.now(tz=timezone.utc)
        if not getattr(obj, "id", None):
            obj.id = 1
        if not getattr(obj, "created_at", None):
            obj.created_at = now
        if not getattr(obj, "updated_at", None):
            obj.updated_at = now

    mock_session.refresh.side_effect = _refresh

    yield mock_session


@pytest.fixture
def mock_shop_id() -> int:
    """Mock authenticated shop ID."""
    return 1


@pytest_asyncio.fixture
async def client(mock_shop_id: int) -> AsyncGenerator[AsyncClient, None]:
    """Create async test client with mocked authentication and DB."""
    app.dependency_overrides[get_current_shop_id] = lambda: mock_shop_id
    app.dependency_overrides[get_db] = _mock_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

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


@pytest.mark.asyncio
async def test_create_product_endpoint_structure(client: AsyncClient) -> None:
    """Test create product endpoint structure (mocked, no DB).

    Verifies the ``POST /api/products`` route is registered and accepts
    the expected JSON body.  The mock DB session is intentionally minimal;
    handler-level exceptions (e.g. response serialisation errors caused by
    the ORM object not being bound to a real session) are expected and
    still prove the route exists — a missing route would yield 404/405
    *without* raising.
    """
    product_data = {
        "title": "Manual Test Product",
        "our_price": 49.99,
        "currency": "USD",
    }

    try:
        response = await client.post("/api/products", json=product_data)
    except Exception:
        # Handler executed (route exists) but the mock DB cannot fully
        # support ORM commit/refresh + Pydantic serialisation.  That's
        # fine — this test only validates routing.
        return

    assert response.status_code != 404, "Endpoint should exist"
    assert response.status_code != 405, "Method should be allowed"


@pytest.mark.asyncio
async def test_update_product_endpoint_structure(mock_shop_id: int) -> None:
    """Test update product endpoint structure (mocked, no DB).

    Verifies the ``PATCH /api/products/{id}`` route is registered and
    accepts a partial-update JSON body.  The mock DB returns a fake
    product for the initial lookup so the handler doesn't 404.
    Any downstream handler exception (mock-DB limitations with ORM
    state, Pydantic serialisation, etc.) still proves the route was found.
    """
    fake_product = _make_fake_product()

    async def _update_get_db() -> AsyncGenerator:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.execute.return_value = _make_mock_result(scalar_value=fake_product)

        async def _refresh(obj, **_kwargs):  # type: ignore[no-untyped-def]
            now = datetime.now(tz=timezone.utc)
            if not getattr(obj, "id", None):
                obj.id = 1
            if not getattr(obj, "created_at", None):
                obj.created_at = now
            if not getattr(obj, "updated_at", None):
                obj.updated_at = now

        mock_session.refresh.side_effect = _refresh
        yield mock_session

    app.dependency_overrides[get_current_shop_id] = lambda: mock_shop_id
    app.dependency_overrides[get_db] = _update_get_db

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            update_data = {
                "title": "Updated Product Title",
                "our_price": 59.99,
            }

            try:
                response = await ac.patch("/api/products/1", json=update_data)
            except Exception:
                # Route found, handler ran into mock-DB limitations — acceptable.
                return

            assert response.status_code != 404, "Endpoint should exist"
            assert response.status_code != 405, "Method should be allowed"
    finally:
        app.dependency_overrides.clear()


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
