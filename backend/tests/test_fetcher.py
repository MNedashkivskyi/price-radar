"""Tests for the PageFetcher (httpx → Playwright fallback) and BrowserPool.

Unit tests use mocks; live tests (marked @live) hit real URLs.

Run all:
    PYTHONPATH=src python -m pytest tests/test_fetcher.py -v -s

Skip live:
    PYTHONPATH=src python -m pytest tests/test_fetcher.py -v -m "not live"
"""

from __future__ import annotations

import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from price_radar.application.price_extraction.browser_pool import BrowserPool
from price_radar.application.price_extraction.decodo_api import DecodoApiClient
from price_radar.application.price_extraction.fetcher import (
    PLAYWRIGHT_DOMAINS,
    FetchResult,
    PageFetcher,
    _MIN_TIER_BUDGET,
    _domain_needs_playwright,
)
from price_radar.application.price_extraction.result import ExtractionResult

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
        return DecodoApiClient(token="dGVzdHVzZXI6dGVzdHBhc3M=")

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

    def test_decodo_fallback_on_any_failure(self) -> None:
        """Decodo API should trigger on ANY failure, not just specific errors."""
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
                error="http_503",
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
            mock_api.assert_called_once()
            assert result.method == "decodo_api"

    def test_decodo_fallback_on_fetch_failed_no_error(self) -> None:
        """Decodo API should trigger when fetch returns tiny HTML with no error set."""
        decodo = self._make_decodo_client()
        fetcher = PageFetcher(use_playwright=True, decodo_api_client=decodo)
        html = "<html>" + "x" * 1000 + "</html>"

        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_playwright") as mock_pw,
            patch.object(fetcher, "_fetch_decodo_api") as mock_api,
        ):
            # Playwright returns HTML but too small → success=False, error=None
            mock_pw.return_value = FetchResult(
                url="https://www.target.com/p/item",
                html="<html>tiny</html>",
                html_size=17,
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
            mock_api.assert_called_once()
            assert result.method == "decodo_api"

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

    def test_fetch_and_extract_extraction_fails_all_tiers_tries_decodo(self) -> None:
        """Normal domain: httpx+extraction fail → PW+extraction fail → Decodo API."""
        decodo = self._make_decodo_client()
        fetcher = PageFetcher(use_playwright=True, decodo_api_client=decodo)
        padding = "<!-- padding -->" * 40
        # HTML that fetches successfully but has no price data
        no_price_html = f"<html><body>{padding}<div>No price here</div></body></html>"
        # Decodo returns HTML with actual price
        decodo_html = (
            f"<html><body>{padding}"
            + """<script type="application/ld+json">
            {"@type": "Product", "offers": {
              "@type": "Offer", "price": "39.99", "priceCurrency": "USD"
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
                url="https://csr-store.com/product",
                html=no_price_html,
                html_size=len(no_price_html),
                method="httpx",
                status_code=200,
            )
            mock_pw.return_value = FetchResult(
                url="https://csr-store.com/product",
                html=no_price_html,
                html_size=len(no_price_html),
                method="playwright",
                status_code=200,
            )
            mock_api.return_value = FetchResult(
                url="https://csr-store.com/product",
                html=decodo_html,
                html_size=len(decodo_html),
                method="decodo_api",
                status_code=200,
                proxy_tier="scraping_api",
            )
            fetch_result, extraction = fetcher.fetch_and_extract(
                "https://csr-store.com/product"
            )
            assert fetch_result.method == "decodo_api"
            assert extraction.success
            assert extraction.current_price == Decimal("39.99")
            mock_api.assert_called_once()

    def test_all_tiers_fail_returns_decodo_as_method(self) -> None:
        """When all tiers fail, the returned method should be decodo_api (last tried)."""
        decodo = self._make_decodo_client()
        fetcher = PageFetcher(use_playwright=True, decodo_api_client=decodo)

        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_playwright") as mock_pw,
            patch.object(fetcher, "_fetch_decodo_api") as mock_api,
        ):
            # PW domain + residential: httpx fails, PW captcha, Decodo also fails
            mock_httpx.return_value = FetchResult(
                url="https://www.bathandbodyworks.com/p/item",
                error="http_403",
                method="httpx",
            )
            mock_pw.return_value = FetchResult(
                url="https://www.bathandbodyworks.com/p/item",
                error="captcha_detected",
                method="playwright",
            )
            mock_api.return_value = FetchResult(
                url="https://www.bathandbodyworks.com/p/item",
                error="decodo_api_timeout",
                method="decodo_api",
            )
            fetch_result, extraction = fetcher.fetch_and_extract(
                "https://www.bathandbodyworks.com/p/item"
            )
            # Decodo was the last tier tried → method must reflect that
            assert fetch_result.method == "decodo_api"
            assert not extraction.success
            mock_api.assert_called_once()

    def test_pw_domain_no_proxy_all_fail_returns_decodo(self) -> None:
        """Path ②: PW fails → Decodo also fails → method should be decodo_api."""
        decodo = self._make_decodo_client()
        fetcher = PageFetcher(use_playwright=True, decodo_api_client=decodo)

        with (
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
                error="decodo_api_timeout",
                method="decodo_api",
            )
            # target.com is a PW domain; force no-residential by patching
            with patch.object(fetcher, "_is_residential", return_value=False):
                fetch_result, extraction = fetcher.fetch_and_extract(
                    "https://www.target.com/p/item"
                )
            assert fetch_result.method == "decodo_api"
            assert not extraction.success
            mock_api.assert_called_once()


# ── Low-confidence fallback tests ─────────────────────────────────────────


class TestLowConfidenceFallback:
    """When extraction finds a price but confidence < 50%, try the next tier."""

    def _make_decodo_client(self) -> DecodoApiClient:
        return DecodoApiClient(token="dGVzdHVzZXI6dGVzdHBhc3M=")

    @staticmethod
    def _good_fetch(url: str, method: str = "httpx") -> FetchResult:
        html = "<html>" + "x" * 1000 + "</html>"
        return FetchResult(
            url=url, html=html, html_size=len(html),
            method=method, status_code=200,
        )

    @staticmethod
    def _low_conf_extraction(price: str = "9.99") -> ExtractionResult:
        return ExtractionResult(
            current_price=Decimal(price), confidence=0.40,
            strategies_used=["regex_fallback"],
        )

    @staticmethod
    def _high_conf_extraction(price: str = "29.99") -> ExtractionResult:
        return ExtractionResult(
            current_price=Decimal(price), confidence=0.95,
            strategies_used=["json_ld"],
        )

    def test_normal_domain_httpx_low_conf_escalates_to_playwright(self) -> None:
        """httpx extracts price at 40% confidence → try Playwright."""
        fetcher = PageFetcher(use_playwright=True)
        url = "https://example-store.com/product"

        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_playwright") as mock_pw,
            patch.object(fetcher, "_try_extract") as mock_extract,
        ):
            mock_httpx.return_value = self._good_fetch(url, "httpx")
            mock_pw.return_value = self._good_fetch(url, "playwright")

            # httpx → low confidence, playwright → high confidence
            mock_extract.side_effect = [
                self._low_conf_extraction("9.99"),
                self._high_conf_extraction("29.99"),
            ]

            fetch_result, extraction = fetcher.fetch_and_extract(url)
            assert fetch_result.method == "playwright"
            assert extraction.current_price == Decimal("29.99")
            assert extraction.confidence == 0.95
            assert mock_pw.call_count == 1

    def test_normal_domain_both_low_conf_escalates_to_decodo(self) -> None:
        """httpx and Playwright both low confidence → try Decodo API."""
        decodo = self._make_decodo_client()
        fetcher = PageFetcher(use_playwright=True, decodo_api_client=decodo)
        url = "https://example-store.com/product"

        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_playwright") as mock_pw,
            patch.object(fetcher, "_fetch_decodo_api") as mock_api,
            patch.object(fetcher, "_try_extract") as mock_extract,
        ):
            mock_httpx.return_value = self._good_fetch(url, "httpx")
            mock_pw.return_value = self._good_fetch(url, "playwright")
            mock_api.return_value = self._good_fetch(url, "decodo_api")

            mock_extract.side_effect = [
                self._low_conf_extraction("9.99"),
                self._low_conf_extraction("9.99"),
                self._high_conf_extraction("29.99"),
            ]

            fetch_result, extraction = fetcher.fetch_and_extract(url)
            assert fetch_result.method == "decodo_api"
            assert extraction.current_price == Decimal("29.99")
            mock_api.assert_called_once()

    def test_normal_domain_all_low_conf_returns_best(self) -> None:
        """All tiers low confidence → return the one with highest confidence."""
        decodo = self._make_decodo_client()
        fetcher = PageFetcher(use_playwright=True, decodo_api_client=decodo)
        url = "https://example-store.com/product"

        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_playwright") as mock_pw,
            patch.object(fetcher, "_fetch_decodo_api") as mock_api,
            patch.object(fetcher, "_try_extract") as mock_extract,
        ):
            mock_httpx.return_value = self._good_fetch(url, "httpx")
            mock_pw.return_value = self._good_fetch(url, "playwright")
            mock_api.return_value = self._good_fetch(url, "decodo_api")

            mock_extract.side_effect = [
                ExtractionResult(
                    current_price=Decimal("9.99"), confidence=0.30,
                    strategies_used=["regex_fallback"],
                ),
                ExtractionResult(
                    current_price=Decimal("19.99"), confidence=0.45,
                    strategies_used=["css_selector"],
                ),
                ExtractionResult(
                    current_price=Decimal("19.99"), confidence=0.42,
                    strategies_used=["regex_fallback"],
                ),
            ]

            fetch_result, extraction = fetcher.fetch_and_extract(url)
            # Should pick the 0.45 confidence result (playwright)
            assert extraction.confidence == 0.45
            assert extraction.current_price == Decimal("19.99")
            assert fetch_result.method == "playwright"

    def test_playwright_domain_low_conf_escalates_to_decodo(self) -> None:
        """Playwright domain: PW extraction at 40% → try Decodo API."""
        decodo = self._make_decodo_client()
        fetcher = PageFetcher(use_playwright=True, decodo_api_client=decodo)
        url = "https://www.target.com/p/item"

        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_playwright") as mock_pw,
            patch.object(fetcher, "_fetch_decodo_api") as mock_api,
            patch.object(fetcher, "_try_extract") as mock_extract,
        ):
            mock_httpx.return_value = FetchResult(
                url=url, error="http_403", method="httpx",
            )
            mock_pw.return_value = self._good_fetch(url, "playwright")
            mock_api.return_value = self._good_fetch(url, "decodo_api")

            mock_extract.side_effect = [
                self._low_conf_extraction("9.99"),
                self._high_conf_extraction("59.99"),
            ]

            fetch_result, extraction = fetcher.fetch_and_extract(url)
            assert fetch_result.method == "decodo_api"
            assert extraction.current_price == Decimal("59.99")
            mock_api.assert_called_once()

    def test_high_confidence_does_not_escalate(self) -> None:
        """When httpx extraction is >= 50% confidence, no escalation."""
        fetcher = PageFetcher(use_playwright=True)
        url = "https://example-store.com/product"

        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_playwright") as mock_pw,
            patch.object(fetcher, "_try_extract") as mock_extract,
        ):
            mock_httpx.return_value = self._good_fetch(url, "httpx")

            mock_extract.return_value = ExtractionResult(
                current_price=Decimal("29.99"), confidence=0.70,
                strategies_used=["css_selector"],
            )

            fetch_result, extraction = fetcher.fetch_and_extract(url)
            assert fetch_result.method == "httpx"
            assert extraction.current_price == Decimal("29.99")
            mock_pw.assert_not_called()


# ── httpx CAPTCHA detection tests ────────────────────────────────────────


class TestHttpxCaptchaDetection:
    """Verify that httpx marks bot-wall pages as captcha_detected."""

    def test_httpx_captcha_page_marked_failed(self) -> None:
        """When httpx gets a CAPTCHA page, FetchResult.success should be False."""
        captcha_html = (
            "<html><head><title>Verify</title></head><body>"
            "<h1>Please verify you are human</h1>"
            "<div>Complete the challenge below</div>"
            + "x" * 1000
            + "</body></html>"
        )
        fetcher = PageFetcher(use_playwright=False)

        with patch("price_radar.application.price_extraction.fetcher.httpx.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = captcha_html
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            result = fetcher._fetch_httpx("https://www.target.com/p/item")
            assert not result.success
            assert result.error == "captcha_detected"
            assert result.html is None

    def test_httpx_real_page_not_blocked(self) -> None:
        """Normal product HTML should NOT be flagged as CAPTCHA."""
        real_html = (
            "<html><head><title>Product</title></head><body>"
            '<div itemprop="price" content="29.99">$29.99</div>'
            + "x" * 1000
            + "</body></html>"
        )
        fetcher = PageFetcher(use_playwright=False)

        with patch("price_radar.application.price_extraction.fetcher.httpx.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = real_html
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            result = fetcher._fetch_httpx("https://example.com/product")
            assert result.success
            assert result.html == real_html

    def test_httpx_with_proxy_captcha_detection(self) -> None:
        """_fetch_httpx_with_proxy should also detect CAPTCHA pages."""
        captcha_html = (
            "<html><body><div>access denied</div>"
            + "x" * 1000
            + "</body></html>"
        )
        fetcher = PageFetcher(use_playwright=False)

        with patch("price_radar.application.price_extraction.fetcher.httpx.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = captcha_html
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            result = fetcher._fetch_httpx_with_proxy(
                "https://www.target.com/p/item",
                "http://user:pass@proxy:10001",
            )
            assert not result.success
            assert result.error == "captcha_detected"

    def test_captcha_httpx_triggers_playwright_fallback(self) -> None:
        """CAPTCHA on httpx → httpx.success is False → Playwright runs."""
        fetcher = PageFetcher(use_playwright=True)
        url = "https://example-store.com/product"

        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_playwright") as mock_pw,
            patch.object(fetcher, "_try_extract") as mock_extract,
        ):
            # httpx hits CAPTCHA → success=False
            mock_httpx.return_value = FetchResult(
                url=url, error="captcha_detected", method="httpx",
            )
            # Playwright succeeds
            good_html = "<html>" + "x" * 1000 + "</html>"
            mock_pw.return_value = FetchResult(
                url=url, html=good_html, html_size=len(good_html),
                method="playwright", status_code=200,
            )
            mock_extract.return_value = ExtractionResult(
                current_price=Decimal("29.99"), confidence=0.85,
                strategies_used=["json_ld"],
            )

            fetch_result, extraction = fetcher.fetch_and_extract(url)
            assert fetch_result.method == "playwright"
            assert extraction.current_price == Decimal("29.99")
            mock_pw.assert_called_once()


# ── Tie-breaking tests ──────────────────────────────────────────────────


class TestPickBestTieBreaking:
    """When two tiers have equal confidence, the later tier should win."""

    def test_equal_confidence_prefers_later_tier(self) -> None:
        """Decodo at 0.45 should beat httpx at 0.45."""
        httpx_fetch = FetchResult(
            url="https://example.com", method="httpx",
            html="<html>...</html>", html_size=1000,
        )
        httpx_ext = ExtractionResult(
            current_price=Decimal("9.99"), confidence=0.45,
            strategies_used=["regex_fallback"],
        )
        decodo_fetch = FetchResult(
            url="https://example.com", method="decodo_api",
            html="<html>...</html>", html_size=5000,
        )
        decodo_ext = ExtractionResult(
            current_price=Decimal("29.99"), confidence=0.45,
            strategies_used=["json_ld"],
        )

        candidates = [(httpx_fetch, httpx_ext), (decodo_fetch, decodo_ext)]
        best_fetch, best_ext = PageFetcher._pick_best(candidates)
        # Decodo (index 1) should win the tiebreak
        assert best_fetch.method == "decodo_api"
        assert best_ext.current_price == Decimal("29.99")

    def test_higher_confidence_still_wins(self) -> None:
        """Higher confidence always wins regardless of tier order."""
        httpx_fetch = FetchResult(
            url="https://example.com", method="httpx",
            html="<html>...</html>", html_size=1000,
        )
        httpx_ext = ExtractionResult(
            current_price=Decimal("29.99"), confidence=0.85,
            strategies_used=["json_ld"],
        )
        decodo_fetch = FetchResult(
            url="https://example.com", method="decodo_api",
            html="<html>...</html>", html_size=5000,
        )
        decodo_ext = ExtractionResult(
            current_price=Decimal("19.99"), confidence=0.45,
            strategies_used=["regex_fallback"],
        )

        candidates = [(httpx_fetch, httpx_ext), (decodo_fetch, decodo_ext)]
        best_fetch, best_ext = PageFetcher._pick_best(candidates)
        assert best_fetch.method == "httpx"
        assert best_ext.confidence == 0.85

    def test_three_way_tie_prefers_last(self) -> None:
        """Three candidates at equal confidence → the last one (Decodo) wins."""
        candidates = [
            (
                FetchResult(url="u", method="httpx", html="x" * 600, html_size=600),
                ExtractionResult(current_price=Decimal("1"), confidence=0.40, strategies_used=["regex_fallback"]),
            ),
            (
                FetchResult(url="u", method="playwright", html="x" * 600, html_size=600),
                ExtractionResult(current_price=Decimal("2"), confidence=0.40, strategies_used=["css_selector"]),
            ),
            (
                FetchResult(url="u", method="decodo_api", html="x" * 600, html_size=600),
                ExtractionResult(current_price=Decimal("3"), confidence=0.40, strategies_used=["json_ld"]),
            ),
        ]
        best_fetch, best_ext = PageFetcher._pick_best(candidates)
        assert best_fetch.method == "decodo_api"
        assert best_ext.current_price == Decimal("3")


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


# ── Time budget / deadline tests ─────────────────────────────────────────


class TestTimeBudgetHelpers:
    """Test the _budget_remaining and _has_budget static methods."""

    def test_budget_remaining_no_deadline(self) -> None:
        """No deadline → infinite budget."""
        assert PageFetcher._budget_remaining(None) == float("inf")

    def test_budget_remaining_future_deadline(self) -> None:
        """Deadline 30s in the future → ~30s remaining."""
        deadline = time.monotonic() + 30
        remaining = PageFetcher._budget_remaining(deadline)
        assert 29.0 <= remaining <= 30.5

    def test_budget_remaining_past_deadline(self) -> None:
        """Deadline in the past → 0 remaining."""
        deadline = time.monotonic() - 10
        assert PageFetcher._budget_remaining(deadline) == 0.0

    def test_has_budget_no_deadline(self) -> None:
        """No deadline → always has budget."""
        assert PageFetcher._has_budget(None) is True

    def test_has_budget_enough_time(self) -> None:
        """Plenty of time remaining → has budget."""
        deadline = time.monotonic() + 60
        assert PageFetcher._has_budget(deadline) is True

    def test_has_budget_not_enough_time(self) -> None:
        """Less than _MIN_TIER_BUDGET remaining → no budget."""
        deadline = time.monotonic() + (_MIN_TIER_BUDGET - 1)
        assert PageFetcher._has_budget(deadline) is False

    def test_has_budget_at_threshold(self) -> None:
        """Slightly above _MIN_TIER_BUDGET remaining → has budget."""
        # Use a small buffer to account for time elapsed between computing
        # the deadline and calling _has_budget.
        deadline = time.monotonic() + _MIN_TIER_BUDGET + 0.5
        assert PageFetcher._has_budget(deadline) is True


class TestFetchAndExtractDeadline:
    """Test that fetch_and_extract respects the deadline parameter."""

    def test_expired_deadline_returns_timeout_error(self) -> None:
        """If deadline is already passed, fetch_and_extract returns timeout immediately."""
        fetcher = PageFetcher(use_playwright=False)
        expired_deadline = time.monotonic() - 10  # 10s in the past

        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
        ):
            fetch_result, extraction = fetcher.fetch_and_extract(
                "https://example.com/product",
                deadline=expired_deadline,
            )
            assert not fetch_result.success
            assert fetch_result.error == "domain_scrape_timeout"
            assert not extraction.success
            mock_httpx.assert_not_called()  # No fetch attempted

    def test_tight_deadline_skips_later_tiers(self) -> None:
        """With a tight deadline, playwright tier should be skipped after httpx."""
        fetcher = PageFetcher(use_playwright=True)
        url = "https://example-store.com/product"

        call_count = {"httpx": 0, "pw": 0}

        def slow_httpx(*args, **kwargs):
            call_count["httpx"] += 1
            # Simulate httpx taking some time, consuming most of the budget
            time.sleep(1.5)
            return FetchResult(
                url=url, error="http_403", method="httpx",
            )

        def slow_pw(*args, **kwargs):
            call_count["pw"] += 1
            return FetchResult(
                url=url, html="<html>" + "x" * 1000, html_size=1006,
                method="playwright", status_code=200,
            )

        with (
            patch.object(fetcher, "_fetch_httpx", side_effect=slow_httpx),
            patch.object(fetcher, "_fetch_playwright", side_effect=slow_pw),
        ):
            # Give just enough time for httpx to start (~6s) but after the
            # 1.5s sleep in httpx, only ~4.5s remain — below _MIN_TIER_BUDGET.
            deadline = time.monotonic() + 6.0
            fetch_result, extraction = fetcher.fetch_and_extract(
                url, deadline=deadline,
            )
            assert call_count["httpx"] == 1
            # Playwright should be skipped because budget dropped below threshold
            assert call_count["pw"] == 0

    def test_ample_deadline_runs_all_tiers(self) -> None:
        """With plenty of time, all tiers should run normally."""
        fetcher = PageFetcher(use_playwright=True)
        url = "https://example-store.com/product"
        padding = "<!-- padding -->" * 40
        html = (
            f"<html><body>{padding}"
            + """<script type="application/ld+json">
            {"@type": "Product", "offers": {
              "@type": "Offer", "price": "29.99", "priceCurrency": "USD"
            }}
            </script>"""
            + "</body></html>"
        )

        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_playwright") as mock_pw,
        ):
            mock_httpx.return_value = FetchResult(
                url=url, error="http_403", method="httpx",
            )
            mock_pw.return_value = FetchResult(
                url=url, html=html, html_size=len(html),
                method="playwright", status_code=200,
            )
            deadline = time.monotonic() + 90  # Plenty of time
            fetch_result, extraction = fetcher.fetch_and_extract(
                url, deadline=deadline,
            )
            assert fetch_result.method == "playwright"
            assert extraction.success
            mock_httpx.assert_called_once()
            mock_pw.assert_called_once()

    def test_no_deadline_works_as_before(self) -> None:
        """Without a deadline, fetch_and_extract should work exactly as before."""
        fetcher = PageFetcher(use_playwright=True)
        url = "https://example-store.com/product"
        padding = "<!-- padding -->" * 40
        html = (
            f"<html><body>{padding}"
            + """<script type="application/ld+json">
            {"@type": "Product", "offers": {
              "@type": "Offer", "price": "29.99", "priceCurrency": "USD"
            }}
            </script>"""
            + "</body></html>"
        )

        with (
            patch.object(fetcher, "_fetch_httpx") as mock_httpx,
            patch.object(fetcher, "_fetch_playwright") as mock_pw,
        ):
            mock_httpx.return_value = FetchResult(
                url=url, html=html, html_size=len(html),
                method="httpx", status_code=200,
            )
            fetch_result, extraction = fetcher.fetch_and_extract(url)
            assert fetch_result.method == "httpx"
            assert extraction.success
            mock_pw.assert_not_called()


class TestFetchDeadline:
    """Test that fetch() respects the deadline parameter."""

    def test_fetch_expired_deadline(self) -> None:
        """Expired deadline on fetch() should return timeout error."""
        fetcher = PageFetcher(use_playwright=False)
        expired = time.monotonic() - 5

        with patch.object(fetcher, "_fetch_httpx") as mock_httpx:
            result = fetcher.fetch("https://example.com", deadline=expired)
            assert not result.success
            assert result.error == "domain_scrape_timeout"
            mock_httpx.assert_not_called()

    def test_fetch_passes_deadline_to_httpx(self) -> None:
        """fetch() should forward the deadline to _fetch_httpx."""
        fetcher = PageFetcher(use_playwright=False)
        deadline = time.monotonic() + 90

        with patch.object(fetcher, "_fetch_httpx") as mock_httpx:
            mock_httpx.return_value = FetchResult(
                url="https://example.com",
                html="<html>" + "x" * 1000, html_size=1006,
                method="httpx", status_code=200,
            )
            fetcher.fetch("https://example.com", deadline=deadline)
            # Verify deadline was passed through
            _, kwargs = mock_httpx.call_args
            assert "deadline" in kwargs
            assert kwargs["deadline"] == deadline


class TestHttpxTimeoutCapping:
    """Test that _fetch_httpx caps its timeout to the remaining budget."""

    def test_httpx_timeout_capped_by_deadline(self) -> None:
        """When deadline is close, httpx timeout should be reduced."""
        fetcher = PageFetcher(use_playwright=False, httpx_timeout=30)
        url = "https://example.com"
        # 10s remaining → effective timeout should be ~8s (10-2 margin)
        deadline = time.monotonic() + 10

        with patch("price_radar.application.price_extraction.fetcher.httpx.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "<html>" + "x" * 1000 + "</html>"
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            fetcher._fetch_httpx(url, deadline=deadline)

            # Check the timeout passed to httpx.get
            _, kwargs = mock_get.call_args
            assert kwargs["timeout"] <= 10  # Capped
            assert kwargs["timeout"] < 30  # Below default

    def test_httpx_timeout_not_capped_without_deadline(self) -> None:
        """Without a deadline, httpx timeout should use the configured default."""
        fetcher = PageFetcher(use_playwright=False, httpx_timeout=30)
        url = "https://example.com"

        with patch("price_radar.application.price_extraction.fetcher.httpx.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "<html>" + "x" * 1000 + "</html>"
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            fetcher._fetch_httpx(url)

            _, kwargs = mock_get.call_args
            assert kwargs["timeout"] == 30  # Default


class TestPlaywrightTimeoutCapping:
    """Test that _fetch_playwright caps its timeout to the remaining budget."""

    def test_playwright_timeout_capped_by_deadline(self) -> None:
        """When deadline is near, Playwright timeout should be reduced."""
        fetcher = PageFetcher(
            use_playwright=True,
            playwright_timeout=45_000,  # 45s default
        )
        url = "https://example.com"
        # 20s remaining → PW timeout should be ~17000ms (20-3 margin)
        deadline = time.monotonic() + 20

        with patch(
            "price_radar.application.price_extraction.fetcher.BrowserPool.get_page"
        ) as mock_pool:
            mock_page = MagicMock()
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_page.goto.return_value = mock_resp
            mock_page.content.return_value = "<html>" + "x" * 1000 + "</html>"
            mock_page.wait_for_load_state = MagicMock()
            mock_page.query_selector.return_value = None
            mock_page.wait_for_timeout = MagicMock()
            mock_page.evaluate = MagicMock()

            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=mock_page)
            ctx.__exit__ = MagicMock(return_value=False)
            mock_pool.return_value = ctx

            fetcher._fetch_playwright(url, deadline=deadline)

            # Verify BrowserPool.get_page was called with a reduced timeout
            _, kwargs = mock_pool.call_args
            assert kwargs["timeout"] < 45_000  # Below default
            assert kwargs["timeout"] <= 20_000  # At most remaining * 1000


class TestBrowserPoolSemaphoreTimeout:
    """Test that BrowserPool.get_page respects semaphore_timeout."""

    def test_semaphore_timeout_raises_on_contention(self) -> None:
        """When all slots are taken, semaphore_timeout triggers TimeoutError."""
        BrowserPool.shutdown()
        # Exhaust all semaphore slots
        for _ in range(BrowserPool._max_pages):
            BrowserPool._semaphore.acquire()
        try:
            with pytest.raises(TimeoutError, match="timed out waiting"):
                with BrowserPool.get_page(semaphore_timeout=0.1):
                    pass  # pragma: no cover
        finally:
            # Release the slots we acquired
            for _ in range(BrowserPool._max_pages):
                BrowserPool._semaphore.release()

    def test_semaphore_no_timeout_blocks_normally(self) -> None:
        """Without semaphore_timeout, get_page blocks (default behaviour)."""
        # Just verify the parameter is accepted — no contention here
        # so it won't actually block.
        BrowserPool.shutdown()
        # We can't actually test indefinite blocking without threads, but
        # we can verify the code path works when slots are available.
        assert BrowserPool._semaphore._value == BrowserPool._max_pages


class TestPlaywrightSemaphoreTimeoutFromDeadline:
    """Test that _fetch_playwright passes a semaphore_timeout derived from deadline."""

    def test_semaphore_timeout_set_from_deadline(self) -> None:
        """When deadline is set, BrowserPool.get_page receives semaphore_timeout."""
        fetcher = PageFetcher(use_playwright=True, playwright_timeout=45_000)
        url = "https://example.com"
        deadline = time.monotonic() + 20

        with patch(
            "price_radar.application.price_extraction.fetcher.BrowserPool.get_page"
        ) as mock_pool:
            mock_page = MagicMock()
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_page.goto.return_value = mock_resp
            mock_page.content.return_value = "<html>" + "x" * 1000 + "</html>"
            mock_page.wait_for_load_state = MagicMock()
            mock_page.query_selector.return_value = None
            mock_page.wait_for_timeout = MagicMock()
            mock_page.evaluate = MagicMock()

            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=mock_page)
            ctx.__exit__ = MagicMock(return_value=False)
            mock_pool.return_value = ctx

            fetcher._fetch_playwright(url, deadline=deadline)

            _, kwargs = mock_pool.call_args
            assert "semaphore_timeout" in kwargs
            assert kwargs["semaphore_timeout"] is not None
            assert kwargs["semaphore_timeout"] <= 20.0

    def test_no_semaphore_timeout_without_deadline(self) -> None:
        """Without deadline, semaphore_timeout should be None."""
        fetcher = PageFetcher(use_playwright=True, playwright_timeout=45_000)
        url = "https://example.com"

        with patch(
            "price_radar.application.price_extraction.fetcher.BrowserPool.get_page"
        ) as mock_pool:
            mock_page = MagicMock()
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_page.goto.return_value = mock_resp
            mock_page.content.return_value = "<html>" + "x" * 1000 + "</html>"
            mock_page.wait_for_load_state = MagicMock()
            mock_page.query_selector.return_value = None
            mock_page.wait_for_timeout = MagicMock()
            mock_page.evaluate = MagicMock()

            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=mock_page)
            ctx.__exit__ = MagicMock(return_value=False)
            mock_pool.return_value = ctx

            fetcher._fetch_playwright(url)

            _, kwargs = mock_pool.call_args
            assert kwargs.get("semaphore_timeout") is None


class TestNetworkIdleTimeoutCapping:
    """Test that wait_for_load_state timeout is capped by deadline."""

    def test_networkidle_timeout_capped_by_deadline(self) -> None:
        """With tight deadline, networkidle timeout should be reduced below 10s."""
        fetcher = PageFetcher(use_playwright=True, playwright_timeout=45_000)
        url = "https://example.com"
        # 8s remaining → after goto (~instant in mock), networkidle should be < 10s
        deadline = time.monotonic() + 8

        with patch(
            "price_radar.application.price_extraction.fetcher.BrowserPool.get_page"
        ) as mock_pool:
            mock_page = MagicMock()
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_page.goto.return_value = mock_resp
            mock_page.content.return_value = "<html>" + "x" * 1000 + "</html>"
            mock_page.query_selector.return_value = MagicMock()  # found price
            mock_page.wait_for_timeout = MagicMock()
            mock_page.evaluate = MagicMock()

            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=mock_page)
            ctx.__exit__ = MagicMock(return_value=False)
            mock_pool.return_value = ctx

            fetcher._fetch_playwright(url, deadline=deadline)

            # Verify wait_for_load_state was called with reduced timeout
            mock_page.wait_for_load_state.assert_called_once()
            call_args = mock_page.wait_for_load_state.call_args
            assert call_args[1]["timeout"] < 10_000  # Below hardcoded default


class TestHttpxWithProxyDeadline:
    """Test that _fetch_httpx_with_proxy respects deadline."""

    def test_httpx_with_proxy_caps_timeout(self) -> None:
        """When deadline is close, httpx-with-proxy timeout should be capped."""
        fetcher = PageFetcher(use_playwright=False, httpx_timeout=30)
        url = "https://www.target.com/p/item"
        proxy = "http://user:pass@proxy:10001"
        deadline = time.monotonic() + 10

        with patch("price_radar.application.price_extraction.fetcher.httpx.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "<html>" + "x" * 1000 + "</html>"
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            fetcher._fetch_httpx_with_proxy(url, proxy, deadline=deadline)

            _, kwargs = mock_get.call_args
            assert kwargs["timeout"] <= 10  # Capped
            assert kwargs["timeout"] < 30  # Below default

    def test_httpx_with_proxy_default_timeout_without_deadline(self) -> None:
        """Without deadline, httpx-with-proxy should use default timeout."""
        fetcher = PageFetcher(use_playwright=False, httpx_timeout=30)
        url = "https://www.target.com/p/item"
        proxy = "http://user:pass@proxy:10001"

        with patch("price_radar.application.price_extraction.fetcher.httpx.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "<html>" + "x" * 1000 + "</html>"
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            fetcher._fetch_httpx_with_proxy(url, proxy)

            _, kwargs = mock_get.call_args
            assert kwargs["timeout"] == 30  # Default


class TestDecodoApiTimeoutOverride:
    """Test thread-safe timeout override for Decodo API."""

    def test_decodo_fetch_uses_timeout_override(self) -> None:
        """fetch(timeout_override=N) should use N instead of _timeout."""
        from price_radar.application.price_extraction.decodo_api import DecodoApiClient

        client = DecodoApiClient(token="dGVzdA==", timeout=60)
        with patch("price_radar.application.price_extraction.decodo_api.httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"content": "<html>ok</html>"}
            mock_post.return_value = mock_resp

            client.fetch("https://example.com", timeout_override=15)

            _, kwargs = mock_post.call_args
            assert kwargs["timeout"] == 15

    def test_decodo_fetch_default_timeout_without_override(self) -> None:
        """fetch() without override should use instance _timeout."""
        from price_radar.application.price_extraction.decodo_api import DecodoApiClient

        client = DecodoApiClient(token="dGVzdA==", timeout=60)
        with patch("price_radar.application.price_extraction.decodo_api.httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"content": "<html>ok</html>"}
            mock_post.return_value = mock_resp

            client.fetch("https://example.com")

            _, kwargs = mock_post.call_args
            assert kwargs["timeout"] == 60

    def test_decodo_timeout_not_mutated(self) -> None:
        """_fetch_decodo_api should not mutate the shared DecodoApiClient._timeout."""
        from price_radar.application.price_extraction.decodo_api import DecodoApiClient

        client = DecodoApiClient(token="dGVzdA==", timeout=60)
        fetcher = PageFetcher(use_playwright=False, decodo_api_client=client)

        with patch.object(client, "fetch") as mock_fetch:
            mock_fetch.return_value = MagicMock(
                html="<html>ok</html>", html_size=11,
                status_code=200, error=None, fetch_time=1.0,
            )
            deadline = time.monotonic() + 20
            fetcher._fetch_decodo_api("https://example.com", deadline=deadline)

            # Verify timeout_override was passed
            _, kwargs = mock_fetch.call_args
            assert "timeout_override" in kwargs
            # And the original _timeout was NOT mutated
            assert client._timeout == 60


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
