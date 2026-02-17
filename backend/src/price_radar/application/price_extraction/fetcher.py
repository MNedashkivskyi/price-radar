"""Two-phase page fetcher: httpx (fast) → Playwright headless (fallback).

``PageFetcher`` transparently tries a lightweight ``httpx`` GET first.
If that fails (bot-blocked) or if the extractor finds no price in the
returned HTML (CSR-only site), the fetcher automatically falls back to a
full Playwright Chromium render.

Production-ready features:
- **Adaptive wait**: polls for price-indicator DOM elements rather than
  a fixed sleep, finishing early on fast sites and waiting longer on slow
  SPAs (up to 8 s).
- **Dynamic Playwright domains**: domains that fail with httpx but succeed
  with Playwright are remembered in a runtime set so subsequent requests
  skip httpx entirely.
- **Retry with exponential backoff**: transient errors (429, 502, 503,
  timeouts) are retried up to 2 times with 1 s → 3 s backoff.
- **CAPTCHA detection**: if Playwright HTML contains challenge keywords
  the request is marked ``captcha_detected`` and not retried.
- **Proxy support**: an optional ``proxy_url`` parameter routes both httpx
  and Playwright through a proxy.

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
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
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
    # Additional domains discovered from 50-site integration test
    "homedepot.com",
    "lowes.com",
    "macys.com",
    "wayfair.com",
    "sephora.com",
    "bathandbodyworks.com",
    "asos.com",
    "rei.com",
    "bhphotovideo.com",
    "adorama.com",
    "barnesandnoble.com",
    "overstock.com",
    "nordstrom.com",
    "dickssportinggoods.com",
    "cb2.com",
    "potterybarn.com",
    "ulta.com",
    "lego.com",
    "chewy.com",
})

# Runtime-learned domains that need Playwright (populated during scraping)
_learned_playwright_domains: set[str] = set()

# ── CAPTCHA detection patterns ───────────────────────────────────────────

# Narrowed to actual CAPTCHA *widget* markers — NOT page text like "security
# check" or "captcha" (which appear in cookie banners, privacy policies, etc.).
_CAPTCHA_PATTERNS = re.compile(
    r"cf-challenge-running|"          # Cloudflare challenge page (active)
    r"cf-turnstile-wrapper|"          # Cloudflare Turnstile widget container
    r'id="px-captcha"|'               # PerimeterX captcha widget
    r'data-callback="onCaptcha"|'     # reCAPTCHA callback attribute
    r"class=\"g-recaptcha\"|"         # Google reCAPTCHA widget
    r"class=\"h-captcha\"|"           # hCaptcha widget
    r"challenge-platform.*managed|"   # Cloudflare managed challenge
    r"<title>Just a moment</title>|"  # Cloudflare interstitial page title
    r"pardon our interruption",       # PerimeterX block page (very specific)
    re.IGNORECASE,
)

# ── Retry configuration ─────────────────────────────────────────────────

_RETRYABLE_STATUS_CODES = {429, 502, 503, 520, 521, 522, 523, 524}
_MAX_RETRIES = 2
_RETRY_BACKOFF = [1.0, 3.0]  # seconds between retries

# ── Price-element polling selectors (for adaptive wait) ──────────────────

_PRICE_INDICATOR_SELECTORS = [
    "[itemprop='price']",
    "script[type='application/ld+json']",
    "[data-price]",
    "[data-product-price]",
    ".price",
    ".product-price",
    "#price",
    ".priceView-customer-price",
    ".a-price",
    "[data-test='product-price']",
]

_PRICE_INDICATOR_JS = """
() => {
    const selectors = %s;
    for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el && el.textContent && el.textContent.trim().length > 0) {
            return true;
        }
    }
    return false;
}
""" % str(_PRICE_INDICATOR_SELECTORS).replace("'", '"')


def _domain_needs_playwright(url: str) -> bool:
    """Check if a URL's domain is in the known Playwright-required set."""
    parsed = urlparse(url)
    domain = (parsed.netloc or "").lower().replace("www.", "")
    # Check exact match (static + learned)
    if domain in PLAYWRIGHT_DOMAINS or domain in _learned_playwright_domains:
        return True
    # Check base domain (e.g., "uk.gymshark.com" → "gymshark.com")
    parts = domain.split(".")
    if len(parts) >= 2:
        base = ".".join(parts[-2:])
        if base in PLAYWRIGHT_DOMAINS or base in _learned_playwright_domains:
            return True
    return False


def _detect_captcha(html: str) -> bool:
    """Check if HTML contains CAPTCHA / bot-challenge indicators."""
    # Only check the first 50KB to avoid scanning huge pages
    sample = html[:50_000]
    return bool(_CAPTCHA_PATTERNS.search(sample))


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
    retries: int = 0  # number of retries performed

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

    Production features:
    - Adaptive wait (polls for price DOM elements, up to 8s)
    - Dynamic Playwright domain learning
    - Retry with exponential backoff on transient errors
    - CAPTCHA detection (avoids wasting retries)
    - Proxy support for both httpx and Playwright

    Args:
        use_playwright: Enable Playwright fallback (default True).
            Set to False for httpx-only mode (faster, but lower success).
        extractor: Optional PriceExtractor instance to reuse.
        rate_limiter: Optional ``DomainRateLimiter`` for per-domain
            throttling.
        circuit_breaker: Optional ``DomainCircuitBreaker``.
        httpx_timeout: Timeout for httpx requests in seconds.
        playwright_timeout: Navigation timeout for Playwright in ms.
        playwright_wait: Max poll time for price elements (seconds).
        rate_limit_max_wait: Max seconds to wait for a rate limit slot.
        proxy_url: Optional proxy URL (``http://user:pass@host:port``).
    """

    def __init__(
        self,
        *,
        use_playwright: bool = True,
        extractor: PriceExtractor | None = None,
        rate_limiter: DomainRateLimiter | None = None,
        circuit_breaker: DomainCircuitBreaker | None = None,
        httpx_timeout: int = 30,
        playwright_timeout: int = 45_000,
        playwright_wait: float = 8.0,
        rate_limit_max_wait: float = 120.0,
        proxy_url: str | None = None,
    ) -> None:
        self._use_playwright = use_playwright
        self._extractor = extractor or PriceExtractor()
        self._rate_limiter = rate_limiter
        self._circuit_breaker = circuit_breaker
        self._httpx_timeout = httpx_timeout
        self._playwright_timeout = playwright_timeout
        self._playwright_wait = playwright_wait
        self._rate_limit_max_wait = rate_limit_max_wait
        self._proxy_url = proxy_url

    # ── Public API ───────────────────────────────────────────────────

    def fetch(self, url: str) -> FetchResult:
        """Fetch a page using httpx, falling back to Playwright if needed.

        Falls back to Playwright when:
        1. httpx returns an HTTP error (403, 503, connection refused, etc.)
        2. The domain is in PLAYWRIGHT_DOMAINS (known to need JS rendering)
        3. httpx succeeds but returns very small HTML (< 500 bytes)
        """
        # Circuit breaker — reject immediately if domain is OPEN
        domain = extract_domain(url)
        if not self._check_circuit(domain):
            return FetchResult(url=url, error="circuit_open")

        # Rate limiting — wait before making any network request
        self._enforce_rate_limit(url)

        needs_pw = _domain_needs_playwright(url)

        # If domain is known to need Playwright, skip httpx entirely
        if needs_pw and self._use_playwright:
            logger.debug("Domain requires Playwright, skipping httpx: %s", url)
            result = self._fetch_playwright(url)
            self._update_circuit(domain, result.success)
            return result

        # Phase 1: Try httpx (fast)
        result = self._fetch_httpx(url)
        if result.success:
            self._update_circuit(domain, True)
            return result

        # Phase 2: Playwright fallback
        if self._use_playwright:
            logger.debug(
                "httpx failed for %s (error=%s), trying Playwright...",
                url, result.error,
            )
            result = self._fetch_playwright(url)
            self._update_circuit(domain, result.success)
            return result

        self._update_circuit(domain, False)
        return result

    def fetch_and_extract(
        self, url: str
    ) -> tuple[FetchResult, ExtractionResult]:
        """Fetch a page and extract the price, with smart fallback.

        Logic:
        1. If domain needs Playwright → Playwright fetch → extract
        2. Else → httpx fetch → extract
        3. If httpx succeeded but extraction found no price → Playwright →
           re-extract (and learn the domain for future requests)
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

        needs_pw = _domain_needs_playwright(url)

        # Known Playwright domains: skip straight to Playwright
        if needs_pw and self._use_playwright:
            pw_fetch = self._fetch_playwright(url)
            extraction = self._try_extract(pw_fetch, url)
            self._update_circuit(domain, extraction.success)
            return pw_fetch, extraction

        # Phase 1: httpx
        httpx_fetch = self._fetch_httpx(url)
        if httpx_fetch.success:
            extraction = self._try_extract(httpx_fetch, url)
            if extraction.success:
                self._update_circuit(domain, True)
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
                        # Learn: this domain needs Playwright for extraction
                        self._learn_playwright_domain(url)
                        self._update_circuit(domain, True)
                        return pw_fetch, pw_extraction
                    # Playwright HTML also didn't extract → return httpx extraction
                    self._update_circuit(domain, False)
                    return pw_fetch, extraction

            self._update_circuit(domain, False)
            return httpx_fetch, extraction

        # httpx fetch failed → Playwright fallback
        if self._use_playwright:
            pw_fetch = self._fetch_playwright(url)
            extraction = self._try_extract(pw_fetch, url)
            if pw_fetch.success and extraction.success:
                # Learn: this domain needs Playwright
                self._learn_playwright_domain(url)
            self._update_circuit(domain, pw_fetch.success and extraction.success)
            return pw_fetch, extraction

        # No Playwright, httpx failed → return empty extraction
        self._update_circuit(domain, False)
        return httpx_fetch, ExtractionResult(confidence=0.0, all_results=[])

    # ── Dynamic Playwright domain learning ────────────────────────────

    @staticmethod
    def _learn_playwright_domain(url: str) -> None:
        """Remember that a domain needs Playwright for future requests."""
        parsed = urlparse(url)
        domain = (parsed.netloc or "").lower().replace("www.", "")
        parts = domain.split(".")
        if len(parts) >= 2:
            base = ".".join(parts[-2:])
        else:
            base = domain
        if base not in PLAYWRIGHT_DOMAINS:
            _learned_playwright_domains.add(base)
            logger.info("Learned Playwright domain: %s", base)

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
        """Fetch page via httpx with retry on transient errors."""
        result = FetchResult(url=url, method="httpx")
        t0 = time.monotonic()
        last_error: str | None = None

        for attempt in range(_MAX_RETRIES + 1):
            if attempt > 0:
                backoff = _RETRY_BACKOFF[min(attempt - 1, len(_RETRY_BACKOFF) - 1)]
                time.sleep(backoff)
                result.retries = attempt

            try:
                proxy_kwargs = {}
                if self._proxy_url:
                    proxy_kwargs["proxy"] = self._proxy_url

                resp = httpx.get(
                    url,
                    headers=_HTTPX_HEADERS,
                    follow_redirects=True,
                    timeout=self._httpx_timeout,
                    **proxy_kwargs,
                )
                resp.raise_for_status()
                result.html = resp.text
                result.status_code = resp.status_code
                result.html_size = len(resp.text)
                result.error = None
                break  # success
            except httpx.HTTPStatusError as e:
                last_error = f"http_{e.response.status_code}"
                result.status_code = e.response.status_code
                # Retry only on transient status codes
                if e.response.status_code not in _RETRYABLE_STATUS_CODES:
                    result.error = last_error
                    break
                result.error = last_error
            except httpx.RequestError as e:
                last_error = f"request_error: {type(e).__name__}"
                result.error = last_error
                # Retry on timeout and connection errors
                if not isinstance(e, (httpx.ConnectTimeout, httpx.ReadTimeout,
                                      httpx.ConnectError, httpx.ReadError)):
                    break

        result.fetch_time = time.monotonic() - t0
        return result

    def _fetch_playwright(self, url: str) -> FetchResult:
        """Fetch page via Playwright with adaptive wait and retry."""
        result = FetchResult(url=url, method="playwright")
        t0 = time.monotonic()
        last_error: str | None = None

        for attempt in range(_MAX_RETRIES + 1):
            if attempt > 0:
                backoff = _RETRY_BACKOFF[min(attempt - 1, len(_RETRY_BACKOFF) - 1)]
                time.sleep(backoff)
                result.retries = attempt

            try:
                pw_kwargs = {}
                if self._proxy_url:
                    pw_kwargs["proxy_server"] = self._proxy_url

                with BrowserPool.get_page(
                    timeout=self._playwright_timeout, **pw_kwargs
                ) as page:
                    resp = page.goto(url, wait_until="domcontentloaded")
                    result.status_code = resp.status if resp else None

                    # Wait for network to settle (reduced from 15s → 10s)
                    try:
                        page.wait_for_load_state("networkidle", timeout=10_000)
                    except Exception:
                        pass  # OK — some sites never fully settle

                    # ── Adaptive wait: poll for price indicators ──────
                    # Instead of a fixed sleep, poll every 500ms for up to
                    # playwright_wait seconds.  Break early if a price
                    # element is found.
                    poll_interval_ms = 500
                    max_polls = int(self._playwright_wait * 1000 / poll_interval_ms)

                    for _ in range(max_polls):
                        try:
                            found = page.evaluate(_PRICE_INDICATOR_JS)
                            if found:
                                break
                        except Exception:
                            pass
                        page.wait_for_timeout(poll_interval_ms)

                    # ── Full-page scroll to trigger lazy loading ─────
                    try:
                        page.evaluate(
                            """
                            async () => {
                                const delay = ms => new Promise(r => setTimeout(r, ms));
                                const h = document.body.scrollHeight;
                                window.scrollTo(0, h * 0.33);
                                await delay(300);
                                window.scrollTo(0, h * 0.66);
                                await delay(300);
                                window.scrollTo(0, h);
                                await delay(300);
                                window.scrollTo(0, 0);
                            }
                            """
                        )
                        page.wait_for_timeout(500)
                    except Exception:
                        pass

                    result.html = page.content()
                    result.html_size = len(result.html)
                    result.error = None

                    # ── CAPTCHA detection ─────────────────────────────
                    # Non-destructive: keep the HTML so extraction
                    # strategies can still try.  Only set the error flag
                    # so callers know the page *may* be a challenge.
                    if result.html and _detect_captcha(result.html):
                        result.error = "captcha_detected"
                        logger.debug("CAPTCHA markers found for %s (HTML kept)", url)
                        break  # Don't retry CAPTCHAs

                    break  # success — no need to retry

            except Exception as e:
                error_name = type(e).__name__
                last_error = f"playwright_error: {error_name}"
                result.error = last_error
                logger.debug("Playwright fetch failed for %s: %s", url, e)
                # Don't retry on non-transient Playwright errors
                if "Target" in error_name or "Browser" in error_name:
                    break

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
