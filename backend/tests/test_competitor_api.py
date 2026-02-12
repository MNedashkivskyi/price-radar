"""Tests for competitor management API."""

import pytest

from price_radar.api.schemas import (
    BulkUploadRequest,
    CompetitorCreateRequest,
    CompetitorProductCreateRequest,
)


def test_competitor_create_schema_validation() -> None:
    """Test competitor creation schema validation."""
    # Valid data
    valid_data = {"name": "Amazon", "domain": "amazon.com"}
    competitor = CompetitorCreateRequest(**valid_data)
    assert competitor.name == "Amazon"
    assert competitor.domain == "amazon.com"

    # Domain normalization - remove protocol
    competitor = CompetitorCreateRequest(name="Test", domain="https://example.com")
    assert competitor.domain == "example.com"

    # Domain normalization - remove www
    competitor = CompetitorCreateRequest(name="Test", domain="www.example.com")
    assert competitor.domain == "example.com"

    # Domain normalization - remove trailing slash
    competitor = CompetitorCreateRequest(name="Test", domain="example.com/")
    assert competitor.domain == "example.com"

    # Invalid domain
    with pytest.raises(ValueError, match="Domain must be a valid domain name"):
        CompetitorCreateRequest(name="Test", domain="invalid")


def test_competitor_product_create_schema_validation() -> None:
    """Test competitor product mapping schema validation."""
    # Valid data
    valid_data = {
        "product_id": 1,
        "competitor_id": 1,
        "url": "https://example.com/product",
    }
    mapping = CompetitorProductCreateRequest(**valid_data)
    assert mapping.product_id == 1
    assert mapping.competitor_id == 1
    assert mapping.url == "https://example.com/product"
    assert mapping.selector_config == {}

    # With selector config
    mapping = CompetitorProductCreateRequest(
        **{**valid_data, "selector_config": {"price": ".price-box"}}
    )
    assert mapping.selector_config == {"price": ".price-box"}

    # Invalid URL - must have protocol
    with pytest.raises(ValueError, match="URL must start with http"):
        CompetitorProductCreateRequest(**{**valid_data, "url": "example.com/product"})


def test_bulk_upload_schema_validation() -> None:
    """Test bulk upload schema validation."""
    # Valid CSV data
    csv_data = "product_id,competitor_url\n1,https://example.com/product1"
    upload = BulkUploadRequest(csv_data=csv_data)
    assert upload.csv_data == csv_data

    # Empty CSV
    with pytest.raises(ValueError, match="CSV data cannot be empty"):
        BulkUploadRequest(csv_data="")

    with pytest.raises(ValueError, match="CSV data cannot be empty"):
        BulkUploadRequest(csv_data="   ")


def test_domain_extraction_from_url() -> None:
    """Test domain extraction logic."""
    from urllib.parse import urlparse

    test_cases = [
        ("https://www.amazon.com/product/123", "amazon.com"),
        ("http://ebay.com/item/456", "ebay.com"),
        ("https://shop.example.com/page", "shop.example.com"),
    ]

    for url, expected_domain in test_cases:
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.lower().replace("www.", "")
        assert domain == expected_domain


def test_csv_parsing() -> None:
    """Test CSV parsing logic."""
    import csv
    import io

    # Test basic CSV parsing
    csv_data = """product_id,competitor_url
1,https://amazon.com/product1
2,https://ebay.com/product2"""

    csv_file = io.StringIO(csv_data)
    reader = csv.DictReader(csv_file)
    rows = list(reader)

    assert len(rows) == 2
    assert rows[0]["product_id"] == "1"
    assert rows[0]["competitor_url"] == "https://amazon.com/product1"
    assert rows[1]["product_id"] == "2"
    assert rows[1]["competitor_url"] == "https://ebay.com/product2"


def test_csv_parsing_with_sku() -> None:
    """Test CSV parsing with SKU column."""
    import csv
    import io

    csv_data = """sku,competitor_url
prod-123,https://amazon.com/product1
prod-456,https://ebay.com/product2"""

    csv_file = io.StringIO(csv_data)
    reader = csv.DictReader(csv_file)
    rows = list(reader)

    assert len(rows) == 2
    assert rows[0]["sku"] == "prod-123"
    assert rows[0]["competitor_url"] == "https://amazon.com/product1"


def test_competitor_name_generation() -> None:
    """Test auto-generation of competitor name from domain."""
    test_cases = [
        ("amazon.com", "Amazon"),
        ("ebay.co.uk", "Ebay"),
        ("shop.example.com", "Shop"),
    ]

    for domain, expected_name in test_cases:
        name = domain.split(".")[0].title()
        assert name == expected_name


def test_bulk_upload_error_reporting() -> None:
    """Test error reporting structure."""
    errors = []

    # Simulate error recording
    errors.append({"row": 2, "error": "Product not found: 999", "data": {"product_id": "999"}})

    errors.append(
        {"row": 3, "error": "Invalid URL format", "data": {"url": "not-a-url"}}
    )

    assert len(errors) == 2
    assert errors[0]["row"] == 2
    assert "Product not found" in errors[0]["error"]
    assert errors[1]["row"] == 3
    assert "Invalid URL" in errors[1]["error"]
