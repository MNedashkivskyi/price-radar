"""Two-phase page fetcher: httpx (fast) → Playwright headless (fallback).

``PageFetcher`` transparently tries a lightweight ``httpx`` GET first.
If that fails (bot-blocked) or if the extractor finds no price in the
returned HTML (CSR-only site), the fetcher automatically falls back to a
full Playwright Chromium render.

Usage::

    from price_radar.application.price_extraction.fetcher import PageFetcher

    fetcher = PageFetcher()
    fetch_result, extraction = fetcher.fetch_and_extract(
        "https://www.target.com/p/keurig-k-mini/-/A-53448183"
    )
    if extraction.success:
        print(extraction.current_price, extraction.currency)

    # At process shutdown:
    PageFetcher.shutdown_browser()
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from price_radar.application.price_extraction.browser_pool import BrowserPool
from price_radar.application.price_extraction.extractor import PriceExtractor
from price_radar.application.price_extraction.result import ExtractionResult

logger = logging.getLogger(__name__)

# ── HTTP headers for httpx requests ──────────────────────────────────────

_HTTPX_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,pl;q=0.8,de;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
}

# ── Domains known to require Playwright ──────────────────────────────────

# Bot-blocked: these sites block simple HTTP requests (403, CAPTCHA, etc.)
# CSR-only: these sites render prices entirely via client-side JavaScript
PLAYWRIGHT_DOMAINS: frozenset[str] = frozenset({
    # Bot-blocked
    "target.com",
    "bestbuy.com",
    "etsy.com",
    "hm.com",
    "uniqlo.com",
    # CSR-only (prices not in initial HTML)
    "newegg.com",
    "aliexpress.com",
    "ikea.com",
    "zara.com",
    # Shopify stores that block API requests
    "gymshark.com",
    "fashionnova.com",
})


def _domain_needs_playwright(url: str) -> bool:
    """Check if a URL's domain is in the known Playwright-required set."""
    parsed = urlparse(url)
    domain = (parsed.netloc or "").lower().replace("www.", "")
    # Check exact match
    if domain in PLAYWRIGHT_DOMAINS:
        return True
    # Check base domain (e.g., "uk.gymshark.com" → "gymshark.com")
    parts = domain.split(".")
    if len(parts) >= 2:
        base = ".".join(parts[-2:])
        if base in PLAYWRIGHT_DOMAINS:
            return True
    return False


# ── Result dataclass ─────────────────────────────────────────────────────

@dataclass
class FetchResult:
    """Result of fetching a page (regardless of method used)."""

    url: str
    html: str | None = None
    method: str = "none"  # "httpx", "playwright", or "none"
    status_code: int | None = None
    error: str | None = None
    fetch_time: float = 0.0
    html_size: int = 0

    @property
    def success(self) -> bool:
        return self.html is not None and self.html_size > 500


# ── PageFetcher ──────────────────────────────────────────────────────────

class PageFetcher:
    """Two-phase page fetcher with automatic Playwright fallback.

    Phase 1 (httpx): Fast HTTP GET (~1-3s). Works for most sites that
    serve server-rendered HTML (Amazon, eBay, Walmart, etc.).

    Phase 2 (Playwright): Full headless Chromium render (~5-15s). Used
    when httpx fails or when the site requires JavaScript execution.

    Args:
        use_playwright: Enable Playwright fallback (default True).
            Set to False for httpx-only mode (faster, but lower success).
        extractor: Optional PriceExtractor instance to reuse.
        httpx_timeout: Timeout for httpx requests in seconds.
        playwright_timeout: Navigation timeout for Playwright in ms.
        playwright_wait: Extra wait time after page load in seconds
            (helps CSR sites finish rendering).
    """

    def __init__(
        self,
        *,
        use_playwright: bool = True,
        extractor: PriceExtractor | None = None,
        httpx_timeout: int = 30,
        playwright_timeout: int = 45_000,
        playwright_wait: float = 2.0,
    ) -> None:
        self._use_playwright = use_playwright
        self._extractor = extractor or PriceExtractor()
        self._httpx_timeout = httpx_timeout
        self._playwright_timeout = playwright_timeout
        self._playwright_wait = playwright_wait

    # ── Public API ───────────────────────────────────────────────────

    def fetch(self, url: str) -> FetchResult:
        """Fetch a page using httpx, falling back to Playwright if needed.

        Falls back to Playwright when:
        1. httpx returns an HTTP error (403, 503, connection refused, etc.)
        2. The domain is in PLAYWRIGHT_DOMAINS (known to need JS rendering)
        3. httpx succeeds but returns very small HTML (< 500 bytes)
        """
        needs_pw = _domain_needs_playwright(url)

        # If domain is known to need Playwright, skip httpx entirely
        if needs_pw and self._use_playwright:
            logger.debug("Domain requires Playwright, skipping httpx: %s", url)
            return self._fetch_playwright(url)

        # Phase 1: Try httpx (fast)
        result = self._fetch_httpx(url)
        if result.success:
            return result

        # Phase 2: Playwright fallback
        if self._use_playwright:
            logger.debug(
                "httpx failed for %s (error=%s), trying Playwright...",
                url, result.error,
            )
            return self._fetch_playwright(url)

        return result

    def fetch_and_extract(
        self, url: str
    ) -> tuple[FetchResult, ExtractionResult]:
        """Fetch a page and extract the price, with smart fallback.

        Logic:
        1. If domain needs Playwright → Playwright fetch → extract
        2. Else → httpx fetch → extract
        3. If httpx succeeded but extraction found no price → Playwright → re-extract
        4. Return best results

        Returns:
            Tuple of (FetchResult, ExtractionResult).
        """
        needs_pw = _domain_needs_playwright(url)

        # Known Playwright domains: skip straight to Playwright
        if needs_pw and self._use_playwright:
            pw_fetch = self._fetch_playwright(url)
            extraction = self._try_extract(pw_fetch, url)
            return pw_fetch, extraction

        # Phase 1: httpx
        httpx_fetch = self._fetch_httpx(url)
        if httpx_fetch.success:
            extraction = self._try_extract(httpx_fetch, url)
            if extraction.success:
                return httpx_fetch, extraction

            # Extraction failed on httpx HTML → try Playwright
            if self._use_playwright:
                logger.debug(
                    "Extraction failed on httpx HTML for %s, trying Playwright...",
                    url,
                )
                pw_fetch = self._fetch_playwright(url)
                if pw_fetch.success:
                    pw_extraction = self._try_extract(pw_fetch, url)
                    if pw_extraction.success:
                        return pw_fetch, pw_extraction
                    # Playwright HTML also didn't extract → return httpx extraction
                    # (might have partial data)
                    return pw_fetch, extraction

            return httpx_fetch, extraction

        # httpx fetch failed → Playwright fallback
        if self._use_playwright:
            pw_fetch = self._fetch_playwright(url)
            extraction = self._try_extract(pw_fetch, url)
            return pw_fetch, extraction

        # No Playwright, httpx failed → return empty extraction
        return httpx_fetch, ExtractionResult(confidence=0.0, all_results=[])

    # ── Internal fetch methods ───────────────────────────────────────

    def _fetch_httpx(self, url: str) -> FetchResult:
        """Fetch page via httpx (lightweight HTTP GET)."""
        result = FetchResult(url=url, method="httpx")
        t0 = time.monotonic()
        try:
            resp = httpx.get(
                url,
                headers=_HTTPX_HEADERS,
                follow_redirects=True,
                timeout=self._httpx_timeout,
            )
            resp.raise_for_status()
            result.html = resp.text
            result.status_code = resp.status_code
            result.html_size = len(resp.text)
        except httpx.HTTPStatusError as e:
            result.error = f"http_{e.response.status_code}"
            result.status_code = e.response.status_code
        except httpx.RequestError as e:
            result.error = f"request_error: {type(e).__name__}"
        finally:
            result.fetch_time = time.monotonic() - t0
        return result

    def _fetch_playwright(self, url: str) -> FetchResult:
        """Fetch page via Playwright headless Chromium."""
        result = FetchResult(url=url, method="playwright")
        t0 = time.monotonic()
        try:
            with BrowserPool.get_page(timeout=self._playwright_timeout) as page:
                resp = page.goto(url, wait_until="domcontentloaded")
                result.status_code = resp.status if resp else None

                # Wait for network to settle (helps CSR sites finish rendering)
                try:
                    page.wait_for_load_state("networkidle", timeout=15_000)
                except Exception:
                    # networkidle timeout is OK — some sites never fully settle
                    pass

                # Extra wait for slow JS rendering
                if self._playwright_wait > 0:
                    page.wait_for_timeout(int(self._playwright_wait * 1000))

                # Scroll down to trigger lazy-loaded price elements
                page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
                page.wait_for_timeout(500)

                result.html = page.content()
                result.html_size = len(result.html)

        except Exception as e:
            error_name = type(e).__name__
            result.error = f"playwright_error: {error_name}"
            logger.debug("Playwright fetch failed for %s: %s", url, e)
        finally:
            result.fetch_time = time.monotonic() - t0

        return result

    # ── Extraction helper ────────────────────────────────────────────

    def _try_extract(self, fetch: FetchResult, url: str) -> ExtractionResult:
        """Run the price extractor on fetched HTML."""
        if not fetch.success or fetch.html is None:
            return ExtractionResult(confidence=0.0, all_results=[])
        try:
            return self._extractor.extract(fetch.html, url)
        except Exception as e:
            logger.exception("Extraction error for %s: %s", url, e)
            return ExtractionResult(confidence=0.0, all_results=[])

    # ── Class-level cleanup ──────────────────────────────────────────

    @staticmethod
    def shutdown_browser() -> None:
        """Convenience: shut down the shared BrowserPool."""
        BrowserPool.shutdown()
