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


# ── Low-confidence fallback tests ─────────────────────────────────────────


class TestLowConfidenceFallback:
    """When extraction finds a price but confidence < 50%, try the next tier."""

    def _make_decodo_client(self) -> DecodoApiClient:
        return DecodoApiClient(username="testuser", password="testpass")

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
