"""Live integration tests for price extraction against real e-commerce URLs.

These tests make real HTTP requests to actual product pages and verify
that the extractor can pull structured price data from them.

Run with:
    PYTHONPATH=src python -m pytest tests/test_price_extraction_live.py -v -s

Marked with `pytest.mark.live` so they can be skipped in CI:
    PYTHONPATH=src python -m pytest -m "not live"
"""

from __future__ import annotations

import pytest
import httpx

from price_radar.application.price_extraction import PriceExtractor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

live = pytest.mark.live


def fetch_page(url: str) -> str:
    """Fetch a real product page, return HTML."""
    resp = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# Amazon.com — Real product page
# ---------------------------------------------------------------------------


@live
class TestAmazonComLive:
    """Live extraction tests against a real Amazon.com product page.

    Product: Cobweb Duster Head Brush (B098R348MK)
    URL: https://www.amazon.com/dp/B098R348MK
    """

    URL = (
        "https://www.amazon.com/Outdoor-Cleaning-Standard-Threaded-Extension"
        "/dp/B098R348MK/ref=sr_1_1_sspa"
    )

    @pytest.fixture(scope="class")
    def extraction_result(self):
        """Fetch the real page once and extract prices."""
        html = fetch_page(self.URL)
        assert len(html) > 10_000, "Page too small — may be a CAPTCHA or redirect"
        extractor = PriceExtractor()
        return extractor.extract(html, self.URL)

    def test_extraction_succeeds(self, extraction_result) -> None:
        """The extractor must find a price on this page."""
        assert extraction_result.success, (
            f"Extraction failed. Strategies attempted: {extraction_result.strategies_used}"
        )

    def test_current_price_is_positive(self, extraction_result) -> None:
        """Current price must be a positive number."""
        assert extraction_result.current_price is not None
        assert extraction_result.current_price > 0

    def test_current_price_reasonable_range(self, extraction_result) -> None:
        """Price should be in a reasonable range for this product ($5–$500)."""
        price = float(extraction_result.current_price)
        assert 5.0 <= price <= 500.0, f"Price {price} outside expected range"

    def test_currency_detected(self, extraction_result) -> None:
        """Currency must be detected (USD or PLN depending on geo)."""
        assert extraction_result.currency in ("USD", "PLN", "EUR", "GBP"), (
            f"Unexpected currency: {extraction_result.currency}"
        )

    def test_in_stock_is_boolean(self, extraction_result) -> None:
        """in_stock must be a boolean."""
        assert isinstance(extraction_result.in_stock, bool)

    def test_confidence_above_threshold(self, extraction_result) -> None:
        """Confidence should be at least moderate (>0.4) for Amazon."""
        assert extraction_result.confidence >= 0.4, (
            f"Low confidence {extraction_result.confidence}. "
            f"Strategies: {extraction_result.strategies_used}"
        )

    def test_css_selector_strategy_used(self, extraction_result) -> None:
        """CSS selector strategy should fire for Amazon (built-in config)."""
        assert "css_selector" in extraction_result.strategies_used, (
            f"css_selector not in strategies: {extraction_result.strategies_used}"
        )

    def test_at_least_two_strategies(self, extraction_result) -> None:
        """Multiple strategies should find a price on Amazon."""
        assert len(extraction_result.strategies_used) >= 2, (
            f"Only {extraction_result.strategies_used} found a price"
        )

    def test_to_dict_complete(self, extraction_result) -> None:
        """to_dict() must return all expected keys with proper types."""
        d = extraction_result.to_dict()
        assert isinstance(d["current_price"], float)
        assert isinstance(d["currency"], str)
        assert isinstance(d["in_stock"], bool)
        assert isinstance(d["confidence"], float)
        assert isinstance(d["strategies_used"], list)
        assert len(d["strategies_used"]) > 0

    def test_result_printable(self, extraction_result) -> None:
        """Print the result for manual inspection during -s runs."""
        d = extraction_result.to_dict()
        print("\n" + "=" * 60)
        print("  LIVE RESULT: Amazon.com (B098R348MK)")
        print("=" * 60)
        print(f"  Current price : {d['current_price']} {d['currency']}")
        print(f"  Original price: {d['original_price']}")
        print(f"  Sale price    : {d['sale_price']}")
        print(f"  In stock      : {d['in_stock']}")
        print(f"  Confidence    : {d['confidence']:.0%}")
        print(f"  Strategies    : {', '.join(d['strategies_used'])}")
        print("=" * 60)
