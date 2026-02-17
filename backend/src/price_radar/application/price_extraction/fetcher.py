"""Two-phase page fetcher: httpx (fast) → Camoufox headless (fallback).

``PageFetcher`` transparently tries a lightweight ``httpx`` GET first.
If that fails (bot-blocked) or if the extractor finds no price in the
returned HTML (CSR-only site), the fetcher automatically falls back to a
full Camoufox (anti-detect Firefox) headless render.

An optional ``DomainRateLimiter`` can be injected to throttle requests
per domain (backed by Redis sliding window counters).

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
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from price_radar.application.price_extraction.browser_pool import BrowserPool
from price_radar.application.price_extraction.extractor import PriceExtractor
from price_radar.application.price_extraction.result import ExtractionResult
from price_radar.application.circuit_breaker import DomainCircuitBreaker
from price_radar.application.rate_limiter import DomainRateLimiter, extract_domain

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

# ── Domains known to require headless browser ────────────────────────────

# Bot-blocked: these sites block simple HTTP requests (403, CAPTCHA, etc.)
# CSR-only: these sites render prices entirely via client-side JavaScript
BROWSER_REQUIRED_DOMAINS: frozenset[str] = frozenset({
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

# Backward-compatible alias
PLAYWRIGHT_DOMAINS = BROWSER_REQUIRED_DOMAINS


def _domain_needs_browser(url: str) -> bool:
    """Check if a URL's domain is in the known browser-required set."""
    parsed = urlparse(url)
    domain = (parsed.netloc or "").lower().replace("www.", "")
    # Check exact match
    if domain in BROWSER_REQUIRED_DOMAINS:
        return True
    # Check base domain (e.g., "uk.gymshark.com" → "gymshark.com")
    parts = domain.split(".")
    if len(parts) >= 2:
        base = ".".join(parts[-2:])
        if base in BROWSER_REQUIRED_DOMAINS:
            return True
    return False

# Backward-compatible alias
_domain_needs_playwright = _domain_needs_browser


# ── Result dataclass ─────────────────────────────────────────────────────

@dataclass
class FetchResult:
    """Result of fetching a page (regardless of method used)."""

    url: str
    html: str | None = None
    method: str = "none"  # "httpx", "camoufox", or "none"
    status_code: int | None = None
    error: str | None = None
    fetch_time: float = 0.0
    html_size: int = 0

    @property
    def success(self) -> bool:
        return self.html is not None and self.html_size > 500


# ── PageFetcher ──────────────────────────────────────────────────────────

class PageFetcher:
    """Two-phase page fetcher with automatic Camoufox fallback.

    Phase 1 (httpx): Fast HTTP GET (~1-3s). Works for most sites that
    serve server-rendered HTML (Amazon, eBay, Walmart, etc.).

    Phase 2 (Camoufox): Full anti-detect Firefox headless render (~5-15s).
    Used when httpx fails or when the site requires JavaScript execution.

    Args:
        use_browser: Enable Camoufox browser fallback (default True).
            Set to False for httpx-only mode (faster, but lower success).
        extractor: Optional PriceExtractor instance to reuse.
        rate_limiter: Optional ``DomainRateLimiter`` for per-domain
            throttling.  When provided, ``wait_for_slot(domain)`` is
            called before every HTTP / browser request.
        circuit_breaker: Optional ``DomainCircuitBreaker``.  When
            provided, the circuit is checked before fetching.  If OPEN,
            the fetch is skipped and a ``FetchResult`` with
            ``error="circuit_open"`` is returned.
        httpx_timeout: Timeout for httpx requests in seconds.
        browser_timeout: Navigation timeout for Camoufox in ms.
        browser_wait: Extra wait time after page load in seconds
            (helps CSR sites finish rendering).
        rate_limit_max_wait: Maximum seconds to wait for a rate limit
            slot before raising ``RateLimitExceeded``.
    """

    def __init__(
        self,
        *,
        use_browser: bool = True,
        use_playwright: bool | None = None,  # backward compat alias
        extractor: PriceExtractor | None = None,
        rate_limiter: DomainRateLimiter | None = None,
        circuit_breaker: DomainCircuitBreaker | None = None,
        httpx_timeout: int = 30,
        browser_timeout: int = 45_000,
        playwright_timeout: int | None = None,  # backward compat alias
        browser_wait: float = 2.0,
        playwright_wait: float | None = None,  # backward compat alias
        rate_limit_max_wait: float = 120.0,
    ) -> None:
        # Resolve backward-compat aliases
        if use_playwright is not None:
            use_browser = use_playwright
        if playwright_timeout is not None:
            browser_timeout = playwright_timeout
        if playwright_wait is not None:
            browser_wait = playwright_wait

        self._use_browser = use_browser
        self._extractor = extractor or PriceExtractor()
        self._rate_limiter = rate_limiter
        self._circuit_breaker = circuit_breaker
        self._httpx_timeout = httpx_timeout
        self._browser_timeout = browser_timeout
        self._browser_wait = browser_wait
        self._rate_limit_max_wait = rate_limit_max_wait

    # ── Public API ───────────────────────────────────────────────────

    def fetch(self, url: str) -> FetchResult:
        """Fetch a page using httpx, falling back to Camoufox if needed.

        If a ``circuit_breaker`` is configured, ``allow_request(domain)``
        is checked first.  If the circuit is OPEN the fetch is skipped.
        On success/failure the circuit breaker is updated.

        If a ``rate_limiter`` is configured, ``wait_for_slot(domain)`` is
        called before the first network request.  The rate limiter is NOT
        called again on Camoufox fallback (one slot per URL, not per
        attempt).

        Falls back to Camoufox when:
        1. httpx returns an HTTP error (403, 503, connection refused, etc.)
        2. The domain is in BROWSER_REQUIRED_DOMAINS (known to need JS rendering)
        3. httpx succeeds but returns very small HTML (< 500 bytes)
        """
        # Circuit breaker — reject immediately if domain is OPEN
        domain = extract_domain(url)
        if not self._check_circuit(domain):
            return FetchResult(url=url, error="circuit_open")

        # Rate limiting — wait before making any network request
        self._enforce_rate_limit(url)

        needs_browser = _domain_needs_browser(url)

        # If domain is known to need a browser, skip httpx entirely
        if needs_browser and self._use_browser:
            logger.debug("Domain requires Camoufox, skipping httpx: %s", url)
            result = self._fetch_camoufox(url)
            self._update_circuit(domain, result.success)
            return result

        # Phase 1: Try httpx (fast)
        result = self._fetch_httpx(url)
        if result.success:
            self._update_circuit(domain, True)
            return result

        # Phase 2: Camoufox fallback
        if self._use_browser:
            logger.debug(
                "httpx failed for %s (error=%s), trying Camoufox...",
                url, result.error,
            )
            result = self._fetch_camoufox(url)
            self._update_circuit(domain, result.success)
            return result

        self._update_circuit(domain, False)
        return result

    def fetch_and_extract(
        self, url: str
    ) -> tuple[FetchResult, ExtractionResult]:
        """Fetch a page and extract the price, with smart fallback.

        If a ``circuit_breaker`` is configured, ``allow_request(domain)``
        is checked first.  On success/failure the circuit is updated.

        If a ``rate_limiter`` is configured, ``wait_for_slot(domain)`` is
        called once before the first network request.

        Logic:
        1. If domain needs browser → Camoufox fetch → extract
        2. Else → httpx fetch → extract
        3. If httpx succeeded but extraction found no price → Camoufox → re-extract
        4. Return best results

        Returns:
            Tuple of (FetchResult, ExtractionResult).
        """
        # Circuit breaker — reject immediately if domain is OPEN
        domain = extract_domain(url)
        if not self._check_circuit(domain):
            return (
                FetchResult(url=url, error="circuit_open"),
                ExtractionResult(confidence=0.0, all_results=[]),
            )

        # Rate limiting — wait before making any network request
        self._enforce_rate_limit(url)

        needs_browser = _domain_needs_browser(url)

        # Known browser-required domains: skip straight to Camoufox
        if needs_browser and self._use_browser:
            cf_fetch = self._fetch_camoufox(url)
            extraction = self._try_extract(cf_fetch, url)
            self._update_circuit(domain, extraction.success)
            return cf_fetch, extraction

        # Phase 1: httpx
        httpx_fetch = self._fetch_httpx(url)
        if httpx_fetch.success:
            extraction = self._try_extract(httpx_fetch, url)
            if extraction.success:
                self._update_circuit(domain, True)
                return httpx_fetch, extraction

            # Extraction failed on httpx HTML → try Camoufox
            if self._use_browser:
                logger.debug(
                    "Extraction failed on httpx HTML for %s, trying Camoufox...",
                    url,
                )
                cf_fetch = self._fetch_camoufox(url)
                if cf_fetch.success:
                    cf_extraction = self._try_extract(cf_fetch, url)
                    if cf_extraction.success:
                        self._update_circuit(domain, True)
                        return cf_fetch, cf_extraction
                    # Camoufox HTML also didn't extract → return httpx extraction
                    # (might have partial data)
                    self._update_circuit(domain, False)
                    return cf_fetch, extraction

            self._update_circuit(domain, False)
            return httpx_fetch, extraction

        # httpx fetch failed → Camoufox fallback
        if self._use_browser:
            cf_fetch = self._fetch_camoufox(url)
            extraction = self._try_extract(cf_fetch, url)
            self._update_circuit(domain, cf_fetch.success and extraction.success)
            return cf_fetch, extraction

        # No browser fallback, httpx failed → return empty extraction
        self._update_circuit(domain, False)
        return httpx_fetch, ExtractionResult(confidence=0.0, all_results=[])

    # ── Circuit breaker ────────────────────────────────────────────────

    def _check_circuit(self, domain: str) -> bool:
        """Return True if the circuit allows the request."""
        if self._circuit_breaker is None:
            return True
        allowed = self._circuit_breaker.allow_request(domain)
        if not allowed:
            logger.info("Circuit OPEN for %s — skipping fetch", domain)
        return allowed

    def _update_circuit(self, domain: str, success: bool) -> None:
        """Update the circuit breaker after a fetch attempt."""
        if self._circuit_breaker is None:
            return
        if success:
            self._circuit_breaker.record_success(domain)
        else:
            self._circuit_breaker.record_failure(domain)

    # ── Rate limiting ──────────────────────────────────────────────────

    def _enforce_rate_limit(self, url: str) -> None:
        """Wait for a rate limit slot if a rate limiter is configured."""
        if self._rate_limiter is None:
            return
        domain = extract_domain(url)
        waited = self._rate_limiter.wait_for_slot(
            domain, max_wait=self._rate_limit_max_wait,
        )
        if waited > 0:
            logger.info(
                "Rate limit: waited %.1fs for slot on %s", waited, domain,
            )

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

    def _fetch_camoufox(self, url: str) -> FetchResult:
        """Fetch page via Camoufox headless Firefox (anti-detect browser)."""
        result = FetchResult(url=url, method="camoufox")
        t0 = time.monotonic()
        try:
            with BrowserPool.get_page(timeout=self._browser_timeout) as page:
                resp = page.goto(url, wait_until="domcontentloaded")
                result.status_code = resp.status if resp else None

                # Wait for network to settle (helps CSR sites finish rendering)
                try:
                    page.wait_for_load_state("networkidle", timeout=15_000)
                except Exception:
                    # networkidle timeout is OK — some sites never fully settle
                    pass

                # Extra wait for slow JS rendering
                if self._browser_wait > 0:
                    page.wait_for_timeout(int(self._browser_wait * 1000))

                # Scroll down to trigger lazy-loaded price elements
                page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
                page.wait_for_timeout(500)

                result.html = page.content()
                result.html_size = len(result.html)

        except Exception as e:
            error_name = type(e).__name__
            result.error = f"camoufox_error: {error_name}"
            logger.debug("Camoufox fetch failed for %s: %s", url, e)
        finally:
            result.fetch_time = time.monotonic() - t0

        return result

    # Backward-compatible alias
    _fetch_playwright = _fetch_camoufox

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
