"""Two-phase page fetcher: httpx (fast) → Playwright headless (fallback).

``PageFetcher`` transparently tries a lightweight ``httpx`` GET first.
If that fails (bot-blocked) or if the extractor finds no price in the
returned HTML (CSR-only site), the fetcher automatically falls back to a
full Playwright Chromium render.

Production-ready features:

- **Proxy-aware**: an optional ``ProxyResolver`` determines per-domain
  whether to use a direct connection or a Decodo residential proxy.
  On 403/429 with DIRECT tier, the fetcher auto-escalates to RESIDENTIAL
  and retries transparently.
- **Rate limiting**: per-domain throttling backed by Redis sliding window.
- **Circuit breaker**: per-domain circuit breaker with exponential backoff.

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
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx

from price_radar.application.price_extraction.browser_pool import BrowserPool
from price_radar.application.price_extraction.extractor import PriceExtractor
from price_radar.application.price_extraction.result import ExtractionResult
from price_radar.application.circuit_breaker import DomainCircuitBreaker
from price_radar.application.proxy_resolver import ProxyResolver, ProxyTier
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
    # Bot-blocked (Cloudflare / PerimeterX / DataDome / Akamai)
    "target.com",
    "bestbuy.com",
    "etsy.com",
    "hm.com",
    "uniqlo.com",
    "macys.com",
    "sephora.com",
    "homedepot.com",
    "lowes.com",
    "asos.com",
    "nordstrom.com",
    "wayfair.com",
    "overstock.com",
    "bathandbodyworks.com",
    "rei.com",
    "barnesandnoble.com",
    "dickssportinggoods.com",
    "cb2.com",
    "vitacost.com",
    "buybuybaby.com",
    # CSR-only (prices not in initial HTML)
    "newegg.com",
    "aliexpress.com",
    "ikea.com",
    "zara.com",
    "bhphotovideo.com",
    "adorama.com",
    "bookshop.org",
    "chubbies.com",
    "ulta.com",
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

# HTTP status codes that trigger proxy escalation (DIRECT → RESIDENTIAL)
_PROXY_ESCALATION_CODES = {403, 429}

# Phrases that indicate a bot-wall / CAPTCHA page instead of real content
_CAPTCHA_INDICATORS: tuple[str, ...] = (
    "verify you are human",
    "are you a robot",
    "captcha",
    "challenge-platform",
    "access denied",
    "blocked",
    "please enable javascript",
    "checking your browser",
    "just a moment",           # Cloudflare interstitial
    "attention required",      # Cloudflare
    "ray id",                  # Cloudflare
    "perimeterx",
    "px-captcha",
    "datadome",
    "bot protection",
    "automated access",
    "security check",
    "human verification",
    "press & hold",            # PerimeterX
)


def _is_captcha_page(html: str) -> bool:
    """Return True if the HTML looks like a bot-wall / CAPTCHA page."""
    if not html or len(html) < 100:
        return False
    # Only check a small prefix — CAPTCHA pages are short
    sample = html[:5000].lower()
    return any(indicator in sample for indicator in _CAPTCHA_INDICATORS)


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
    proxy_tier: str = "direct"  # "direct" or "residential"

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

    Proxy routing: when a ``ProxyResolver`` is provided, each request is
    routed through the resolver's per-domain classification.  If a direct
    request fails with 403/429, the domain is automatically escalated to
    the residential proxy tier and the request is retried.

    Args:
        use_playwright: Enable Playwright fallback (default True).
            Set to False for httpx-only mode (faster, but lower success).
        extractor: Optional PriceExtractor instance to reuse.
        rate_limiter: Optional ``DomainRateLimiter`` for per-domain
            throttling.
        circuit_breaker: Optional ``DomainCircuitBreaker``.
        proxy_resolver: Optional ``ProxyResolver`` for per-domain proxy
            routing.  When provided, requests are transparently routed
            through direct or residential proxy.
        httpx_timeout: Timeout for httpx requests in seconds.
        playwright_timeout: Navigation timeout for Playwright in ms.
        playwright_wait: Extra wait time after page load in seconds
            (helps CSR sites finish rendering).
        rate_limit_max_wait: Maximum seconds to wait for a rate limit
            slot before raising ``RateLimitExceeded``.
    """

    def __init__(
        self,
        *,
        use_playwright: bool = True,
        extractor: PriceExtractor | None = None,
        rate_limiter: DomainRateLimiter | None = None,
        circuit_breaker: DomainCircuitBreaker | None = None,
        proxy_resolver: ProxyResolver | None = None,
        httpx_timeout: int = 30,
        playwright_timeout: int = 45_000,
        playwright_wait: float = 2.0,
        rate_limit_max_wait: float = 120.0,
    ) -> None:
        self._use_playwright = use_playwright
        self._extractor = extractor or PriceExtractor()
        self._rate_limiter = rate_limiter
        self._circuit_breaker = circuit_breaker
        self._proxy_resolver = proxy_resolver
        self._httpx_timeout = httpx_timeout
        self._playwright_timeout = playwright_timeout
        self._playwright_wait = playwright_wait
        self._rate_limit_max_wait = rate_limit_max_wait

    # ── Public API ───────────────────────────────────────────────────

    def _is_residential(self, url: str) -> bool:
        """Return True if the domain resolves to the RESIDENTIAL proxy tier."""
        if self._proxy_resolver is None:
            return False
        domain = extract_domain(url)
        return self._proxy_resolver.resolve(domain) == ProxyTier.RESIDENTIAL

    def fetch(self, url: str) -> FetchResult:
        """Fetch a page using httpx, falling back to Playwright if needed.

        If a ``circuit_breaker`` is configured, ``allow_request(domain)``
        is checked first.  If the circuit is OPEN the fetch is skipped.
        On success/failure the circuit breaker is updated.

        If a ``rate_limiter`` is configured, ``wait_for_slot(domain)`` is
        called before the first network request.  The rate limiter is NOT
        called again on Playwright fallback (one slot per URL, not per
        attempt).

        Falls back to Playwright when:
        1. httpx returns an HTTP error (403, 503, connection refused, etc.)
        2. The domain is in PLAYWRIGHT_DOMAINS (known to need JS rendering)
        3. httpx succeeds but returns very small HTML (< 500 bytes)

        When the domain needs Playwright but has a RESIDENTIAL proxy, httpx
        is tried first (with proxy) because httpx handles proxy auth better.
        Playwright is the fallback.
        """
        # Circuit breaker — reject immediately if domain is OPEN
        domain = extract_domain(url)
        if not self._check_circuit(domain):
            return FetchResult(url=url, error="circuit_open")

        # Rate limiting — wait before making any network request
        self._enforce_rate_limit(url)

        needs_pw = _domain_needs_playwright(url)
        residential = self._is_residential(url)

        # If domain needs Playwright BUT has a residential proxy, try
        # httpx+proxy first — httpx handles proxy auth correctly and is
        # much faster than Playwright.
        if needs_pw and residential:
            logger.debug(
                "Domain %s needs Playwright but has RESIDENTIAL proxy — "
                "trying httpx+proxy first",
                url,
            )
            result = self._fetch_httpx(url)
            if result.success:
                self._update_circuit(domain, True)
                return result
            # httpx+proxy failed → fall through to Playwright+proxy
            logger.debug(
                "httpx+proxy failed for %s (error=%s), trying Playwright...",
                url, result.error,
            )
            if self._use_playwright:
                result = self._fetch_playwright(url)
                self._update_circuit(domain, result.success)
                return result
            self._update_circuit(domain, False)
            return result

        # If domain is known to need Playwright (no proxy), skip httpx
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

        If a ``circuit_breaker`` is configured, ``allow_request(domain)``
        is checked first.  On success/failure the circuit is updated.

        If a ``rate_limiter`` is configured, ``wait_for_slot(domain)`` is
        called once before the first network request.

        Logic:
        1. If domain needs Playwright AND has RESIDENTIAL proxy →
           try httpx+proxy first (fast, better auth support), then
           Playwright+proxy as fallback.
        2. If domain needs Playwright (no proxy) → Playwright fetch → extract
        3. Else → httpx fetch → extract
        4. If httpx succeeded but extraction found no price → Playwright → re-extract
        5. Return best results

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
        residential = self._is_residential(url)

        # Residential + Playwright domain: try httpx+proxy FIRST, then
        # fall through to Playwright+proxy.  httpx handles proxy auth
        # correctly and is ~10× faster than Playwright.
        if needs_pw and residential:
            logger.debug(
                "Domain %s needs Playwright but has RESIDENTIAL proxy — "
                "trying httpx+proxy first",
                url,
            )
            httpx_fetch = self._fetch_httpx(url)
            if httpx_fetch.success:
                extraction = self._try_extract(httpx_fetch, url)
                if extraction.success:
                    self._update_circuit(domain, True)
                    return httpx_fetch, extraction
                # httpx HTML didn't extract — fall through to Playwright
                logger.debug(
                    "httpx+proxy got HTML but extraction failed for %s, "
                    "trying Playwright+proxy...",
                    url,
                )

            # httpx failed or extraction failed → try Playwright+proxy
            if self._use_playwright:
                pw_fetch = self._fetch_playwright(url)
                extraction = self._try_extract(pw_fetch, url)
                self._update_circuit(domain, extraction.success)
                return pw_fetch, extraction

            # No Playwright → return httpx result
            self._update_circuit(domain, False)
            return httpx_fetch, ExtractionResult(confidence=0.0, all_results=[])

        # Known Playwright domains (no residential proxy): skip to Playwright
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
                        self._update_circuit(domain, True)
                        return pw_fetch, pw_extraction
                    # Playwright HTML also didn't extract → return httpx extraction
                    # (might have partial data)
                    self._update_circuit(domain, False)
                    return pw_fetch, extraction

            self._update_circuit(domain, False)
            return httpx_fetch, extraction

        # httpx fetch failed → Playwright fallback
        if self._use_playwright:
            pw_fetch = self._fetch_playwright(url)
            extraction = self._try_extract(pw_fetch, url)
            self._update_circuit(domain, pw_fetch.success and extraction.success)
            return pw_fetch, extraction

        # No Playwright, httpx failed → return empty extraction
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

    def _resolve_proxy(self, url: str) -> tuple[str | None, str]:
        """Resolve the proxy URL and tier for a given page URL.

        Returns:
            Tuple of (proxy_url_or_None, tier_name).
        """
        if self._proxy_resolver is None:
            return None, "direct"
        domain = extract_domain(url)
        proxy_url = self._proxy_resolver.get_proxy_url(domain)
        tier = self._proxy_resolver.resolve(domain)
        return proxy_url, tier.value

    def _escalate_proxy(self, url: str) -> str | None:
        """Escalate a domain to RESIDENTIAL and return the new proxy URL.

        Returns None if no proxy is configured or escalation isn't possible.
        """
        if self._proxy_resolver is None or not self._proxy_resolver.has_proxy:
            return None
        domain = extract_domain(url)
        self._proxy_resolver.escalate(domain)
        return self._proxy_resolver.get_proxy_url(domain)

    def _fetch_httpx(self, url: str) -> FetchResult:
        """Fetch page via httpx with transparent proxy routing.

        If the initial request fails with 403/429 and the current tier
        is DIRECT, automatically escalates to RESIDENTIAL and retries.
        """
        proxy_url, tier = self._resolve_proxy(url)
        result = FetchResult(url=url, method="httpx", proxy_tier=tier)
        t0 = time.monotonic()

        try:
            proxy_kwargs: dict = {}
            if proxy_url:
                proxy_kwargs["proxy"] = proxy_url

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
        except httpx.HTTPStatusError as e:
            result.error = f"http_{e.response.status_code}"
            result.status_code = e.response.status_code

            # Auto-escalate: if DIRECT got 403/429, retry via RESIDENTIAL
            if (
                tier == "direct"
                and e.response.status_code in _PROXY_ESCALATION_CODES
            ):
                escalated_proxy = self._escalate_proxy(url)
                if escalated_proxy:
                    logger.info(
                        "Escalating %s to residential proxy after HTTP %d",
                        url, e.response.status_code,
                    )
                    result = self._fetch_httpx_with_proxy(url, escalated_proxy)
                    result.fetch_time = time.monotonic() - t0
                    return result

        except httpx.RequestError as e:
            result.error = f"request_error: {type(e).__name__}"
        finally:
            if result.fetch_time == 0.0:
                result.fetch_time = time.monotonic() - t0

        return result

    def _fetch_httpx_with_proxy(
        self, url: str, proxy_url: str
    ) -> FetchResult:
        """Fetch page via httpx through a specific proxy (no escalation)."""
        result = FetchResult(url=url, method="httpx", proxy_tier="residential")
        try:
            resp = httpx.get(
                url,
                headers=_HTTPX_HEADERS,
                follow_redirects=True,
                timeout=self._httpx_timeout,
                proxy=proxy_url,
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
        return result

    def _fetch_playwright(self, url: str) -> FetchResult:
        """Fetch page via Playwright headless Chromium with proxy support.

        Includes:
        - Adaptive wait: polls for price elements every 500 ms (up to 8 s)
        - CAPTCHA detection: marks bot-wall pages as ``captcha_detected``
        - Full-page scroll to trigger lazy-loaded content
        """
        proxy_url, tier = self._resolve_proxy(url)
        result = FetchResult(url=url, method="playwright", proxy_tier=tier)
        t0 = time.monotonic()

        try:
            pw_kwargs: dict = {}
            if proxy_url:
                pw_kwargs["proxy_server"] = proxy_url

            # Residential proxies add 2-10s latency per hop; give them
            # extra time so we don't timeout on the proxy handshake.
            pw_timeout = self._playwright_timeout
            if proxy_url:
                pw_timeout = max(pw_timeout, 60_000)

            with BrowserPool.get_page(
                timeout=pw_timeout, **pw_kwargs
            ) as page:
                resp = page.goto(url, wait_until="domcontentloaded")
                result.status_code = resp.status if resp else None

                # Wait for network to settle (helps CSR sites finish rendering)
                try:
                    page.wait_for_load_state("networkidle", timeout=10_000)
                except Exception:
                    # networkidle timeout is OK — some sites never fully settle
                    pass

                # ── Early CAPTCHA detection ────────────────────────────
                # Check immediately after load — if it's a bot wall, skip
                # the expensive polling + scrolling to save ~5 s per site.
                early_html = page.content()
                if _is_captcha_page(early_html):
                    logger.info(
                        "CAPTCHA/bot-wall detected for %s (tier=%s, %d bytes)",
                        url, tier, len(early_html),
                    )
                    result.error = "captcha_detected"
                    result.html = None
                    result.html_size = 0
                    result.fetch_time = time.monotonic() - t0
                    return result

                # ── Adaptive wait: poll for price elements ────────────
                # Poll every 500 ms for up to 3 s.  Most real product
                # pages render price within 1-2 s of networkidle; if it's
                # not there after 3 s it likely won't appear.
                _PRICE_SELECTOR = (
                    "[itemprop='price'], [data-price], .price, "
                    "script[type='application/ld+json'], "
                    "[class*='price' i], [class*='Price' i], "
                    "[data-testid*='price' i]"
                )
                found_price_el = False
                for _ in range(6):  # 6 × 500 ms = 3 s max
                    try:
                        el = page.query_selector(_PRICE_SELECTOR)
                        if el:
                            found_price_el = True
                            break
                    except Exception:
                        pass
                    page.wait_for_timeout(500)

                if not found_price_el:
                    logger.debug(
                        "No price element found after polling for %s", url,
                    )

                # ── Scroll to trigger lazy-loaded content ─────────────
                page.evaluate(
                    "window.scrollTo(0, document.body.scrollHeight / 3)"
                )
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
