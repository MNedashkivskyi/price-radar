"""Lazy-singleton Camoufox browser pool for headless page rendering.

Manages a single reusable Camoufox (anti-detect Firefox) browser instance.
The browser is created lazily on first ``get_page()`` call and stays alive
until ``shutdown()`` is called (or process exit).

Camoufox applies anti-detection at the C++ engine level (patched Firefox),
so no JavaScript stealth scripts are needed — unlike the previous Playwright
Chromium approach.

Usage::

    from price_radar.application.price_extraction.browser_pool import BrowserPool

    with BrowserPool.get_page() as page:
        page.goto("https://example.com", wait_until="networkidle")
        html = page.content()

    # At process shutdown:
    BrowserPool.shutdown()
"""

from __future__ import annotations

import atexit
import logging
import threading
from contextlib import contextmanager
from typing import Any, Generator

logger = logging.getLogger(__name__)


class BrowserPool:
    """Thread-safe lazy-singleton managing a Camoufox (Firefox) browser.

    Anti-detection features (handled by Camoufox at C++ level):
    - Real Firefox fingerprint (OS, CPU, navigator, fonts, WebGL, etc.)
    - No ``navigator.webdriver`` leak
    - No automation markers in the DOM
    - BrowserForge-generated device characteristics

    Concurrency:
    - A ``threading.Semaphore`` limits the number of pages open at once
      (default 3) to avoid resource exhaustion.
    """

    _lock = threading.Lock()
    _browser: Any = None  # playwright.sync_api.Browser (lazy import)
    _camoufox_cm: Any = None  # camoufox.sync_api.Camoufox context manager
    _initialised = False
    _max_pages = 3
    _semaphore = threading.Semaphore(_max_pages)

    # ── Lifecycle ────────────────────────────────────────────────────

    @classmethod
    def _ensure_browser(cls) -> Any:
        """Lazily launch the Camoufox browser (double-checked locking)."""
        if cls._browser is not None:
            return cls._browser

        with cls._lock:
            if cls._browser is not None:
                return cls._browser

            logger.info("BrowserPool: launching Camoufox (headless Firefox)...")

            # Lazy import — camoufox may not be installed in test environments
            from camoufox.sync_api import Camoufox

            # Lazy config import to avoid circular dependency and allow test mocking
            try:
                from price_radar.infrastructure.config import settings
                headless = settings.camoufox_headless
                os_fingerprint = settings.camoufox_os
                geoip = settings.camoufox_geoip
                block_webrtc = settings.camoufox_block_webrtc
            except Exception:
                headless = True
                os_fingerprint = "linux"
                geoip = True
                block_webrtc = True

            cls._camoufox_cm = Camoufox(
                headless=headless,
                os=os_fingerprint,
                geoip=geoip,
                block_webrtc=block_webrtc,
                enable_cache=True,
            )
            cls._browser = cls._camoufox_cm.__enter__()
            cls._initialised = True
            atexit.register(cls.shutdown)
            logger.info("BrowserPool: Camoufox ready")
            return cls._browser

    @classmethod
    def shutdown(cls) -> None:
        """Close the browser and Camoufox.  Safe to call multiple times."""
        with cls._lock:
            if cls._camoufox_cm is not None:
                try:
                    cls._camoufox_cm.__exit__(None, None, None)
                except Exception:
                    pass
                cls._camoufox_cm = None
                cls._browser = None

            cls._initialised = False
            logger.info("BrowserPool: shutdown complete")

    # ── Page Management ──────────────────────────────────────────────

    @classmethod
    @contextmanager
    def get_page(
        cls,
        *,
        timeout: int = 60_000,
    ) -> Generator[Any, None, None]:
        """Yield a fresh Playwright-compatible ``Page`` in a new browser context.

        The context (and page) are destroyed when the context-manager exits.
        A semaphore limits the number of concurrent pages.

        Args:
            timeout: Default navigation timeout in milliseconds.
        """
        cls._semaphore.acquire()
        context: Any = None
        try:
            browser = cls._ensure_browser()
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id="America/New_York",
                java_script_enabled=True,
                ignore_https_errors=True,
            )
            page = context.new_page()
            page.set_default_navigation_timeout(timeout)
            page.set_default_timeout(timeout)
            yield page
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            cls._semaphore.release()

    # ── Introspection ────────────────────────────────────────────────

    @classmethod
    def is_running(cls) -> bool:
        """Return True if the browser is currently alive."""
        return cls._browser is not None and cls._initialised
