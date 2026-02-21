"""Decodo Web Scraping API client.

Provides a thin wrapper around the Decodo (formerly Smartproxy) Web Scraping
API.  The API handles proxies, browser rendering, CAPTCHA solving, and
anti-bot bypass internally, returning clean HTML.

This is the **last-resort** fetch tier.  It is used when both httpx and
Playwright have failed (e.g. the site uses advanced anti-bot like
PerimeterX, DataDome, or Akamai Bot Manager).

Endpoint: ``POST https://scraper-api.decodo.com/v2/scrape``

Authentication: ``Authorization: Basic <token>`` header, where ``<token>``
is the pre-built Base64 token from the Decodo dashboard.

Requires a Decodo **Web Scraping API** subscription (Core or Advanced).
The ``headless=html`` parameter requires an **Advanced** subscription for
JavaScript rendering.

Environment variable: ``DECODO_API_TOKEN``

Usage::

    from price_radar.application.price_extraction.decodo_api import DecodoApiClient

    client = DecodoApiClient(token="Base64TokenHere==")
    result = client.fetch("https://www.target.com/p/...")
    if result.success:
        print(result.html[:200])
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# ── API configuration ────────────────────────────────────────────────────

_DECODO_API_URL = "https://scraper-api.decodo.com/v2/scrape"
_DECODO_API_TIMEOUT = 60  # seconds — the API does its own retries internally


@dataclass
class DecodoApiResult:
    """Result from a Decodo Scraping API call."""

    url: str
    html: str | None = None
    status_code: int | None = None
    error: str | None = None
    fetch_time: float = 0.0
    html_size: int = 0

    @property
    def success(self) -> bool:
        return self.html is not None and self.html_size > 500


class DecodoApiClient:
    """Client for the Decodo Web Scraping API.

    Args:
        token: Decodo API Base64 token (from dashboard Scraper tab →
            Authentication).  Sent as ``Authorization: Basic <token>``.
        headless: Enable JavaScript rendering.  Set to ``"html"`` for
            full browser rendering (requires Advanced plan) or ``None``
            for raw HTTP fetch (Core plan).
        geo: Geographic location code (e.g. ``"United States"``).
        device_type: Device type (``"desktop"``, ``"mobile"``).
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        *,
        token: str,
        headless: str | None = "html",
        geo: str = "United States",
        device_type: str = "desktop",
        timeout: int = _DECODO_API_TIMEOUT,
    ) -> None:
        self._token = token
        self._headless = headless
        self._geo = geo
        self._device_type = device_type
        self._timeout = timeout

    @property
    def is_configured(self) -> bool:
        """Return True if the token is set."""
        return bool(self._token)

    def fetch(
        self, url: str, *, timeout_override: int | None = None,
    ) -> DecodoApiResult:
        """Fetch a page through the Decodo Scraping API.

        Sends a POST request with ``target=universal`` and returns the
        rendered HTML.

        Args:
            url: The product page URL to scrape.
            timeout_override: Optional per-call timeout (seconds).  When
                provided, overrides the instance-level ``_timeout`` without
                mutating shared state (thread-safe).

        Returns:
            DecodoApiResult with HTML content or error details.
        """
        result = DecodoApiResult(url=url)
        t0 = time.monotonic()

        if not self.is_configured:
            result.error = "decodo_api_not_configured"
            return result

        effective_timeout = timeout_override if timeout_override is not None else self._timeout

        payload: dict = {
            "target": "universal",
            "url": url,
            "geo": self._geo,
            "device_type": self._device_type,
        }
        if self._headless:
            payload["headless"] = self._headless

        try:
            resp = httpx.post(
                _DECODO_API_URL,
                json=payload,
                headers={
                    "Authorization": f"Basic {self._token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=effective_timeout,
            )

            result.status_code = resp.status_code

            if resp.status_code == 200:
                data = resp.json()
                # The API returns HTML in the "results" array or "content" field
                content = self._extract_content(data)
                if content:
                    result.html = content
                    result.html_size = len(content)
                else:
                    result.error = "decodo_api_empty_response"
            elif resp.status_code == 401:
                result.error = "decodo_api_auth_failed"
            elif resp.status_code == 422:
                result.error = f"decodo_api_invalid_params: {resp.text[:100]}"
            else:
                result.error = f"decodo_api_http_{resp.status_code}"

        except httpx.TimeoutException:
            result.error = "decodo_api_timeout"
        except httpx.RequestError as e:
            result.error = f"decodo_api_error: {type(e).__name__}"
        except Exception as e:
            result.error = f"decodo_api_error: {type(e).__name__}: {str(e)[:80]}"
        finally:
            result.fetch_time = time.monotonic() - t0

        if result.success:
            logger.info(
                "Decodo API success for %s (%d bytes, %.1fs)",
                url, result.html_size, result.fetch_time,
            )
        else:
            logger.info(
                "Decodo API failed for %s: %s (%.1fs)",
                url, result.error, result.fetch_time,
            )

        return result

    @staticmethod
    def _extract_content(data: dict) -> str | None:
        """Extract HTML content from the Decodo API response.

        The response format varies between sync and async endpoints.
        This handles the common formats:

        - ``{"results": [{"content": "<html>..."}]}``
        - ``{"content": "<html>..."}``
        """
        # Format 1: results array (most common)
        results = data.get("results")
        if isinstance(results, list) and results:
            first = results[0]
            if isinstance(first, dict):
                content = first.get("content")
                if content:
                    return content

        # Format 2: top-level content field
        content = data.get("content")
        if content:
            return content

        # Format 3: the data itself might be a string (raw HTML)
        if isinstance(data, str):
            return data

        return None
