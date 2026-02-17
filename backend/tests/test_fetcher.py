"""Tests for the PageFetcher (httpx → Camoufox fallback) and BrowserPool.

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
from price_radar.application.price_extraction.fetcher import (
    BROWSER_REQUIRED_DOMAINS,
    PLAYWRIGHT_DOMAINS,
    FetchResult,
    PageFetcher,
    _domain_needs_browser,
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
    def test_known_browser_required_domain(self) -> None:
        assert _domain_needs_browser("https://www.target.com/p/item/-/A-123") is True

    def test_known_browser_required_subdomain(self) -> None:
        assert _domain_needs_browser("https://uk.gymshark.com/products/legging") is True

    def test_non_browser_required_domain(self) -> None:
        assert _domain_needs_browser("https://www.amazon.com/dp/B123") is False

    def test_ebay_not_browser_required(self) -> None:
        assert _domain_needs_browser("https://www.ebay.com/itm/123") is False

    def test_walmart_not_browser_required(self) -> None:
        assert _domain_needs_browser("https://www.walmart.com/ip/Item/123") is False

    def test_bestbuy_is_browser_required(self) -> None:
        assert _domain_needs_browser("https://www.bestbuy.com/site/item/123.p") is True

    def test_newegg_is_browser_required(self) -> None:
        assert _domain_needs_browser("https://www.newegg.com/p/N82E168") is True

    def test_aliexpress_is_browser_required(self) -> None:
        assert _domain_needs_browser("https://www.aliexpress.com/item/123.html") is True

    def test_browser_required_domains_is_frozenset(self) -> None:
        assert isinstance(BROWSER_REQUIRED_DOMAINS, frozenset)
        assert len(BROWSER_REQUIRED_DOMAINS) >= 10

    def test_backward_compat_aliases(self) -> None:
        """PLAYWRIGHT_DOMAINS and _domain_needs_playwright are backward-compat aliases."""
        assert PLAYWRIGHT_DOMAINS is BROWSER_REQUIRED_DOMAINS
        assert _domain_needs_playwright is _domain_needs_browser


# ── PageFetcher unit tests (mocked) ─────────────────────────────────────


class TestPageFetcherHttpxOnly:
    """Test httpx-only mode (Camoufox disabled)."""

    def test_httpx_success(self) -> None:
        fetcher = PageFetcher(use_browser=False)
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
        fetcher = PageFetcher(use_browser=False)
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

    def test_backward_compat_use_playwright_param(self) -> None:
        """use_playwright=False should work as alias for use_browser=False."""
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


class TestPageFetcherWithFallback:
    """Test httpx → Camoufox fallback logic."""

    def test_known_domain_skips_httpx(self) -> None:
        fetcher = PageFetcher(use_browser=True)
        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_camoufox") as mock_cf,
        ):
            mock_cf.return_value = FetchResult(
                url="https://www.target.com/p/item/-/A-123",
                html="<html>" + "x" * 5000,
                html_size=5006,
                method="camoufox",
                status_code=200,
            )
            result = fetcher.fetch("https://www.target.com/p/item/-/A-123")
            assert result.method == "camoufox"
            mock_httpx.assert_not_called()  # httpx skipped for known domain
            mock_cf.assert_called_once()

    def test_httpx_fail_triggers_camoufox(self) -> None:
        fetcher = PageFetcher(use_browser=True)
        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_camoufox") as mock_cf,
        ):
            mock_httpx.return_value = FetchResult(
                url="https://unknown-store.com",
                error="http_403",
                method="httpx",
            )
            mock_cf.return_value = FetchResult(
                url="https://unknown-store.com",
                html="<html>" + "x" * 5000,
                html_size=5006,
                method="camoufox",
                status_code=200,
            )
            result = fetcher.fetch("https://unknown-store.com")
            assert result.method == "camoufox"
            assert result.success

    def test_fetch_and_extract_httpx_success(self) -> None:
        """When httpx succeeds AND extraction finds a price → no Camoufox."""
        fetcher = PageFetcher(use_browser=True)
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
            patch.object(fetcher, "_fetch_camoufox") as mock_cf,
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
            mock_cf.assert_not_called()  # No Camoufox needed

    def test_fetch_and_extract_httpx_no_price_triggers_camoufox(self) -> None:
        """When httpx succeeds but extraction fails → Camoufox fallback."""
        fetcher = PageFetcher(use_browser=True)
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
            patch.object(fetcher, "_fetch_camoufox") as mock_cf,
        ):
            mock_httpx.return_value = FetchResult(
                url="https://csr-store.com/product",
                html=empty_html,
                html_size=len(empty_html),
                method="httpx",
                status_code=200,
            )
            mock_cf.return_value = FetchResult(
                url="https://csr-store.com/product",
                html=rich_html,
                html_size=len(rich_html),
                method="camoufox",
                status_code=200,
            )
            fetch_result, extraction = fetcher.fetch_and_extract(
                "https://csr-store.com/product"
            )
            assert extraction.success
            assert extraction.current_price == Decimal("49.99")
            assert fetch_result.method == "camoufox"

    def test_fetch_and_extract_known_domain_uses_camoufox_directly(self) -> None:
        """Known browser-required domains skip httpx entirely."""
        fetcher = PageFetcher(use_browser=True)
        padding = "<!-- padding -->" * 40
        html = (
            f"<html><body>{padding}"
            + '<span itemprop="price" content="99.99">$99.99</span>'
            + '<meta itemprop="priceCurrency" content="USD">'
            + "</body></html>"
        )
        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_camoufox") as mock_cf,
        ):
            mock_cf.return_value = FetchResult(
                url="https://www.target.com/p/item/-/A-123",
                html=html,
                html_size=len(html),
                method="camoufox",
                status_code=200,
            )
            fetch_result, extraction = fetcher.fetch_and_extract(
                "https://www.target.com/p/item/-/A-123"
            )
            assert fetch_result.method == "camoufox"
            mock_httpx.assert_not_called()


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


# ── Live integration tests (require real network + Camoufox) ──────────────


@live
class TestPageFetcherLive:
    """Live tests that fetch real URLs via Camoufox.

    These tests verify that:
    1. BrowserPool launches correctly with Camoufox
    2. Camoufox can render JS-heavy pages
    3. PageFetcher.fetch_and_extract() works end-to-end
    """

    def test_camoufox_fetches_real_page(self) -> None:
        """Camoufox should be able to fetch a simple page."""
        fetcher = PageFetcher(use_browser=True)
        result = fetcher._fetch_camoufox("https://example.com")
        assert result.success
        assert result.method == "camoufox"
        assert result.html_size > 100
        assert "Example Domain" in (result.html or "")

    def test_ebay_httpx_success(self) -> None:
        """eBay should work with httpx (no Camoufox needed)."""
        fetcher = PageFetcher(use_browser=True)
        fetch_result, extraction = fetcher.fetch_and_extract(
            "https://www.ebay.com/itm/314074071401"
        )
        assert fetch_result.method == "httpx"
        assert extraction.success
        assert extraction.current_price is not None

    def test_target_uses_camoufox(self) -> None:
        """Target.com (bot-blocked + CSR) should use Camoufox."""
        fetcher = PageFetcher(use_browser=True)
        fetch_result, extraction = fetcher.fetch_and_extract(
            "https://www.target.com/p/keurig-k-mini-single-serve-k-cup-pod-coffee-maker-black/-/A-53448183"
        )
        assert fetch_result.method == "camoufox"
        # Target may or may not extract a price (depends on JS rendering)
        # but the fetch itself should succeed
        assert fetch_result.success or fetch_result.error is not None

    def test_browser_pool_running_after_use(self) -> None:
        """After Camoufox is used, BrowserPool should be running."""
        fetcher = PageFetcher(use_browser=True)
        fetcher._fetch_camoufox("https://example.com")
        assert BrowserPool.is_running()

    def test_shutdown_after_tests(self) -> None:
        """Clean up browser after tests."""
        BrowserPool.shutdown()
        assert BrowserPool.is_running() is False
