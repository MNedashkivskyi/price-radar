"""Formal error categorization for scraping failures.

Every raw error string produced by the fetcher or extractor is classified
into one of the :class:`ScrapeErrorCategory` members so that downstream
consumers (monitoring, alerting, dead-letter queue) can act on broad
categories rather than parsing ad-hoc strings.

Usage::

    from price_radar.application.scrape_errors import (
        ScrapeErrorCategory,
        categorize_error,
    )

    category = categorize_error("captcha_detected")
    assert category is ScrapeErrorCategory.CAPTCHA
"""

from __future__ import annotations

from enum import Enum


class ScrapeErrorCategory(str, Enum):
    """Broad categories for scraping failures."""

    BLOCKED = "blocked"
    """Site returned 403 / access-denied (non-CAPTCHA bot block)."""

    CAPTCHA = "captcha"
    """CAPTCHA or interactive bot-wall page detected."""

    TIMEOUT = "timeout"
    """Request, Playwright, or domain-level scrape timeout."""

    PARSE_FAILED = "parse_failed"
    """HTML fetched successfully but price extraction found nothing."""

    SITE_DOWN = "site_down"
    """Connection refused, DNS failure, 5xx, or similar server-side error."""

    RATE_LIMITED = "rate_limited"
    """HTTP 429 or internal per-domain rate limiter exceeded."""

    CIRCUIT_OPEN = "circuit_open"
    """Domain circuit breaker is OPEN — request was never attempted."""

    SELECTOR_BROKEN = "selector_broken"
    """Custom CSS selector did not match any element (site redesigned?)."""

    UNKNOWN = "unknown"
    """Could not classify the error string."""


def categorize_error(error: str | None) -> ScrapeErrorCategory:
    """Map a raw error string to a :class:`ScrapeErrorCategory`.

    The function matches substrings in priority order (most specific first)
    so overlapping patterns resolve correctly.

    Args:
        error: The raw error string from ``FetchResult.error`` or
            ``ScrapeResult.error``.  ``None`` maps to ``UNKNOWN``.

    Returns:
        The matching error category.
    """
    if not error:
        return ScrapeErrorCategory.UNKNOWN

    low = error.lower()

    # ── Most specific first ──────────────────────────────────────────

    if "captcha" in low:
        return ScrapeErrorCategory.CAPTCHA

    if "circuit_open" in low:
        return ScrapeErrorCategory.CIRCUIT_OPEN

    if "rate_limit" in low:
        return ScrapeErrorCategory.RATE_LIMITED

    if "http_429" in low:
        return ScrapeErrorCategory.RATE_LIMITED

    if "timeout" in low:
        return ScrapeErrorCategory.TIMEOUT

    if "http_403" in low:
        return ScrapeErrorCategory.BLOCKED

    if "extraction_failed" in low or "extraction_found_no_price" in low:
        return ScrapeErrorCategory.PARSE_FAILED

    if "selector" in low:
        return ScrapeErrorCategory.SELECTOR_BROKEN

    # Server-side / network errors → site_down
    if any(
        marker in low
        for marker in (
            "http_5",
            "connection",
            "dns",
            "request_error",
            "connecterror",
            "remotedisconnected",
        )
    ):
        return ScrapeErrorCategory.SITE_DOWN

    # Playwright protocol errors often indicate network-level failure
    if "playwright_error" in low and "err_" in low:
        return ScrapeErrorCategory.SITE_DOWN

    return ScrapeErrorCategory.UNKNOWN
