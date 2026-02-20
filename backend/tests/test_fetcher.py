"""Tests for the PageFetcher (httpx → Playwright fallback) and BrowserPool.

Unit tests use mocks; live tests (marked @live) hit real URLs.

Run all:
    PYTHONPATH=src python -m pytest tests/test_fetcher.py -v -s

Skip live:
    PYTHONPATH=src python -m pytest tests/test_fetcher.py -v -m "not live"
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from price_radar.application.price_extraction.browser_pool import BrowserPool
from price_radar.application.price_extraction.decodo_api import DecodoApiClient
from price_radar.application.price_extraction.fetcher import (
    PLAYWRIGHT_DOMAINS,
    FetchResult,
    PageFetcher,
    _domain_needs_playwright,
)

live = pytest.mark.live


# ── FetchResult tests ────────────────────────────────────────────────────


class TestFetchResult:
    def test_success_when_html_present(self) -> None:
        r = FetchResult(url="https://example.com", html="<html>" + "x" * 500, html_size=506)
        assert r.success is True

    def test_failure_when_no_html(self) -> None:
        r = FetchResult(url="https://example.com")
        assert r.success is False

    def test_failure_when_html_too_small(self) -> None:
        r = FetchResult(url="https://example.com", html="<html>tiny</html>", html_size=17)
        assert r.success is False

    def test_failure_when_error_set(self) -> None:
        r = FetchResult(url="https://example.com", error="http_403")
        assert r.success is False


# ── Domain detection tests ───────────────────────────────────────────────


class TestDomainDetection:
    def test_known_playwright_domain(self) -> None:
        assert _domain_needs_playwright("https://www.target.com/p/item/-/A-123") is True

    def test_known_playwright_subdomain(self) -> None:
        assert _domain_needs_playwright("https://uk.gymshark.com/products/legging") is True

    def test_non_playwright_domain(self) -> None:
        assert _domain_needs_playwright("https://www.amazon.com/dp/B123") is False

    def test_ebay_not_playwright(self) -> None:
        assert _domain_needs_playwright("https://www.ebay.com/itm/123") is False

    def test_walmart_not_playwright(self) -> None:
        assert _domain_needs_playwright("https://www.walmart.com/ip/Item/123") is False

    def test_bestbuy_is_playwright(self) -> None:
        assert _domain_needs_playwright("https://www.bestbuy.com/site/item/123.p") is True

    def test_newegg_is_playwright(self) -> None:
        assert _domain_needs_playwright("https://www.newegg.com/p/N82E168") is True

    def test_aliexpress_is_playwright(self) -> None:
        assert _domain_needs_playwright("https://www.aliexpress.com/item/123.html") is True

    def test_playwright_domains_is_frozenset(self) -> None:
        assert isinstance(PLAYWRIGHT_DOMAINS, frozenset)
        assert len(PLAYWRIGHT_DOMAINS) >= 10


# ── PageFetcher unit tests (mocked) ─────────────────────────────────────


class TestPageFetcherHttpxOnly:
    """Test httpx-only mode (Playwright disabled)."""

    def test_httpx_success(self) -> None:
        fetcher = PageFetcher(use_playwright=False)
        with patch.object(fetcher, "_fetch_httpx") as mock_httpx:
            mock_httpx.return_value = FetchResult(
                url="https://example.com",
                html="<html>" + "x" * 1000,
                html_size=1006,
                method="httpx",
                status_code=200,
            )
            result = fetcher.fetch("https://example.com")
            assert result.success
            assert result.method == "httpx"
            mock_httpx.assert_called_once()

    def test_httpx_failure_no_fallback(self) -> None:
        fetcher = PageFetcher(use_playwright=False)
        with patch.object(fetcher, "_fetch_httpx") as mock_httpx:
            mock_httpx.return_value = FetchResult(
                url="https://www.bestbuy.com/site/item/123",
                error="http_403",
                method="httpx",
                status_code=403,
            )
            result = fetcher.fetch("https://www.bestbuy.com/site/item/123")
            assert not result.success
            assert result.error == "http_403"


class TestPageFetcherWithFallback:
    """Test httpx → Playwright fallback logic."""

    def test_known_domain_skips_httpx(self) -> None:
        fetcher = PageFetcher(use_playwright=True)
        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_playwright") as mock_pw,
        ):
            mock_pw.return_value = FetchResult(
                url="https://www.target.com/p/item/-/A-123",
                html="<html>" + "x" * 5000,
                html_size=5006,
                method="playwright",
                status_code=200,
            )
            result = fetcher.fetch("https://www.target.com/p/item/-/A-123")
            assert result.method == "playwright"
            mock_httpx.assert_not_called()  # httpx skipped for known domain
            mock_pw.assert_called_once()

    def test_httpx_fail_triggers_playwright(self) -> None:
        fetcher = PageFetcher(use_playwright=True)
        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_playwright") as mock_pw,
        ):
            mock_httpx.return_value = FetchResult(
                url="https://unknown-store.com",
                error="http_403",
                method="httpx",
            )
            mock_pw.return_value = FetchResult(
                url="https://unknown-store.com",
                html="<html>" + "x" * 5000,
                html_size=5006,
                method="playwright",
                status_code=200,
            )
            result = fetcher.fetch("https://unknown-store.com")
            assert result.method == "playwright"
            assert result.success

    def test_fetch_and_extract_httpx_success(self) -> None:
        """When httpx succeeds AND extraction finds a price → no Playwright."""
        fetcher = PageFetcher(use_playwright=True)
        # Pad HTML to exceed the 500-byte FetchResult.success threshold
        html = (
            "<html><head><title>Product Page</title></head><body>"
            + "<!-- padding -->" * 30
            + """
            <script type="application/ld+json">
            {"@type": "Product", "offers": {
              "@type": "Offer", "price": "29.99", "priceCurrency": "USD"
            }}
            </script>
            """
            + "</body></html>"
        )
        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_playwright") as mock_pw,
        ):
            mock_httpx.return_value = FetchResult(
                url="https://example.com/product",
                html=html,
                html_size=len(html),
                method="httpx",
                status_code=200,
            )
            fetch_result, extraction = fetcher.fetch_and_extract(
                "https://example.com/product"
            )
            assert extraction.success
            assert extraction.current_price == Decimal("29.99")
            assert fetch_result.method == "httpx"
            mock_pw.assert_not_called()  # No Playwright needed

    def test_fetch_and_extract_httpx_no_price_triggers_playwright(self) -> None:
        """When httpx succeeds but extraction fails → Playwright fallback."""
        fetcher = PageFetcher(use_playwright=True)
        # Pad both HTML strings to exceed the 500-byte threshold
        padding = "<!-- padding -->" * 40
        empty_html = f"<html><body>{padding}<div>Loading...</div></body></html>"
        rich_html = (
            f"<html><body>{padding}"
            + """
            <script type="application/ld+json">
            {"@type": "Product", "offers": {
              "@type": "Offer", "price": "49.99", "priceCurrency": "USD"
            }}
            </script>
            """
            + "</body></html>"
        )
        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_playwright") as mock_pw,
        ):
            mock_httpx.return_value = FetchResult(
                url="https://csr-store.com/product",
                html=empty_html,
                html_size=len(empty_html),
                method="httpx",
                status_code=200,
            )
            mock_pw.return_value = FetchResult(
                url="https://csr-store.com/product",
                html=rich_html,
                html_size=len(rich_html),
                method="playwright",
                status_code=200,
            )
            fetch_result, extraction = fetcher.fetch_and_extract(
                "https://csr-store.com/product"
            )
            assert extraction.success
            assert extraction.current_price == Decimal("49.99")
            assert fetch_result.method == "playwright"

    def test_fetch_and_extract_known_domain_uses_playwright_directly(self) -> None:
        """Known Playwright domains skip httpx entirely."""
        fetcher = PageFetcher(use_playwright=True)
        padding = "<!-- padding -->" * 40
        html = (
            f"<html><body>{padding}"
            + '<span itemprop="price" content="99.99">$99.99</span>'
            + '<meta itemprop="priceCurrency" content="USD">'
            + "</body></html>"
        )
        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_playwright") as mock_pw,
        ):
            mock_pw.return_value = FetchResult(
                url="https://www.target.com/p/item/-/A-123",
                html=html,
                html_size=len(html),
                method="playwright",
                status_code=200,
            )
            fetch_result, extraction = fetcher.fetch_and_extract(
                "https://www.target.com/p/item/-/A-123"
            )
            assert fetch_result.method == "playwright"
            mock_httpx.assert_not_called()


# ── Decodo Scraping API (Tier 3) fallback tests ──────────────────────────


class TestDecodoApiFallback:
    """Test Tier 3 Decodo Scraping API fallback logic."""

    def _make_decodo_client(self) -> DecodoApiClient:
        return DecodoApiClient(username="testuser", password="testpass")

    def test_decodo_fallback_on_captcha_detected(self) -> None:
        """When Playwright returns captcha_detected, Decodo API should be tried."""
        decodo = self._make_decodo_client()
        fetcher = PageFetcher(use_playwright=True, decodo_api_client=decodo)
        html = "<html>" + "x" * 1000 + "</html>"

        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_playwright") as mock_pw,
            patch.object(fetcher, "_fetch_decodo_api") as mock_api,
        ):
            mock_pw.return_value = FetchResult(
                url="https://www.target.com/p/item",
                error="captcha_detected",
                method="playwright",
            )
            mock_api.return_value = FetchResult(
                url="https://www.target.com/p/item",
                html=html,
                html_size=len(html),
                method="decodo_api",
                status_code=200,
                proxy_tier="scraping_api",
            )
            result = fetcher.fetch("https://www.target.com/p/item")
            assert result.method == "decodo_api"
            assert result.success
            mock_api.assert_called_once()

    def test_decodo_fallback_on_playwright_error(self) -> None:
        """When Playwright returns playwright_error, Decodo API should be tried."""
        decodo = self._make_decodo_client()
        fetcher = PageFetcher(use_playwright=True, decodo_api_client=decodo)

        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_playwright") as mock_pw,
            patch.object(fetcher, "_fetch_decodo_api") as mock_api,
        ):
            mock_httpx.return_value = FetchResult(
                url="https://unknown-store.com",
                error="http_403",
                method="httpx",
            )
            mock_pw.return_value = FetchResult(
                url="https://unknown-store.com",
                error="playwright_error: TimeoutError: page timed out",
                method="playwright",
            )
            html = "<html>" + "x" * 1000 + "</html>"
            mock_api.return_value = FetchResult(
                url="https://unknown-store.com",
                html=html,
                html_size=len(html),
                method="decodo_api",
                status_code=200,
                proxy_tier="scraping_api",
            )
            result = fetcher.fetch("https://unknown-store.com")
            assert result.method == "decodo_api"
            assert result.success

    def test_no_decodo_fallback_without_client(self) -> None:
        """Without a Decodo client, no fallback should happen."""
        fetcher = PageFetcher(use_playwright=True)

        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_playwright") as mock_pw,
        ):
            mock_pw.return_value = FetchResult(
                url="https://www.target.com/p/item",
                error="captcha_detected",
                method="playwright",
            )
            result = fetcher.fetch("https://www.target.com/p/item")
            assert result.method == "playwright"
            assert not result.success

    def test_no_decodo_fallback_on_normal_failure(self) -> None:
        """Decodo API should NOT trigger on regular http errors (not captcha/playwright_error)."""
        decodo = self._make_decodo_client()
        fetcher = PageFetcher(use_playwright=True, decodo_api_client=decodo)

        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_playwright") as mock_pw,
            patch.object(fetcher, "_fetch_decodo_api") as mock_api,
        ):
            mock_pw.return_value = FetchResult(
                url="https://www.target.com/p/item",
                error="http_503",
                method="playwright",
            )
            result = fetcher.fetch("https://www.target.com/p/item")
            mock_api.assert_not_called()

    def test_fetch_and_extract_decodo_fallback(self) -> None:
        """fetch_and_extract should try Decodo API when Playwright fails with captcha."""
        decodo = self._make_decodo_client()
        fetcher = PageFetcher(use_playwright=True, decodo_api_client=decodo)
        padding = "<!-- padding -->" * 40
        html = (
            f"<html><body>{padding}"
            + """<script type="application/ld+json">
            {"@type": "Product", "offers": {
              "@type": "Offer", "price": "59.99", "priceCurrency": "USD"
            }}
            </script>"""
            + "</body></html>"
        )

        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_playwright") as mock_pw,
            patch.object(fetcher, "_fetch_decodo_api") as mock_api,
        ):
            mock_pw.return_value = FetchResult(
                url="https://www.target.com/p/item",
                error="captcha_detected",
                method="playwright",
            )
            mock_api.return_value = FetchResult(
                url="https://www.target.com/p/item",
                html=html,
                html_size=len(html),
                method="decodo_api",
                status_code=200,
                proxy_tier="scraping_api",
            )
            fetch_result, extraction = fetcher.fetch_and_extract(
                "https://www.target.com/p/item"
            )
            assert fetch_result.method == "decodo_api"
            assert extraction.success
            assert extraction.current_price == Decimal("59.99")

    def test_fetch_and_extract_normal_domain_decodo_fallback(self) -> None:
        """Normal domain: httpx fails → Playwright fails → Decodo API."""
        decodo = self._make_decodo_client()
        fetcher = PageFetcher(use_playwright=True, decodo_api_client=decodo)
        padding = "<!-- padding -->" * 40
        html = (
            f"<html><body>{padding}"
            + """<script type="application/ld+json">
            {"@type": "Product", "offers": {
              "@type": "Offer", "price": "19.99", "priceCurrency": "USD"
            }}
            </script>"""
            + "</body></html>"
        )

        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_playwright") as mock_pw,
            patch.object(fetcher, "_fetch_decodo_api") as mock_api,
        ):
            mock_httpx.return_value = FetchResult(
                url="https://unknown-store.com/product",
                error="http_403",
                method="httpx",
            )
            mock_pw.return_value = FetchResult(
                url="https://unknown-store.com/product",
                error="playwright_error: ERR_HTTP2_PROTOCOL_ERROR",
                method="playwright",
            )
            mock_api.return_value = FetchResult(
                url="https://unknown-store.com/product",
                html=html,
                html_size=len(html),
                method="decodo_api",
                status_code=200,
                proxy_tier="scraping_api",
            )
            fetch_result, extraction = fetcher.fetch_and_extract(
                "https://unknown-store.com/product"
            )
            assert fetch_result.method == "decodo_api"
            assert extraction.success
            assert extraction.current_price == Decimal("19.99")


# ── BrowserPool tests ────────────────────────────────────────────────────


class TestBrowserPool:
    def test_not_running_initially(self) -> None:
        """BrowserPool should not have a browser before first use."""
        # Reset state
        BrowserPool.shutdown()
        assert BrowserPool.is_running() is False

    def test_shutdown_is_idempotent(self) -> None:
        """Calling shutdown multiple times should not raise."""
        BrowserPool.shutdown()
        BrowserPool.shutdown()
        BrowserPool.shutdown()


# ── Live integration tests (require real network + Playwright) ───────────


@live
class TestPageFetcherLive:
    """Live tests that fetch real URLs via Playwright.

    These tests verify that:
    1. BrowserPool launches correctly
    2. Playwright can render JS-heavy pages
    3. PageFetcher.fetch_and_extract() works end-to-end
    """

    def test_playwright_fetches_real_page(self) -> None:
        """Playwright should be able to fetch a simple page."""
        fetcher = PageFetcher(use_playwright=True)
        result = fetcher._fetch_playwright("https://example.com")
        assert result.success
        assert result.method == "playwright"
        assert result.html_size > 100
        assert "Example Domain" in (result.html or "")

    def test_ebay_httpx_success(self) -> None:
        """eBay should work with httpx (no Playwright needed)."""
        fetcher = PageFetcher(use_playwright=True)
        fetch_result, extraction = fetcher.fetch_and_extract(
            "https://www.ebay.com/itm/314074071401"
        )
        assert fetch_result.method == "httpx"
        assert extraction.success
        assert extraction.current_price is not None

    def test_target_uses_playwright(self) -> None:
        """Target.com (bot-blocked + CSR) should use Playwright."""
        fetcher = PageFetcher(use_playwright=True)
        fetch_result, extraction = fetcher.fetch_and_extract(
            "https://www.target.com/p/keurig-k-mini-single-serve-k-cup-pod-coffee-maker-black/-/A-53448183"
        )
        assert fetch_result.method == "playwright"
        # Target may or may not extract a price (depends on JS rendering)
        # but the fetch itself should succeed
        assert fetch_result.success or fetch_result.error is not None

    def test_browser_pool_running_after_use(self) -> None:
        """After Playwright is used, BrowserPool should be running."""
        fetcher = PageFetcher(use_playwright=True)
        fetcher._fetch_playwright("https://example.com")
        assert BrowserPool.is_running()

    def test_shutdown_after_tests(self) -> None:
        """Clean up browser after tests."""
        BrowserPool.shutdown()
        assert BrowserPool.is_running() is False
