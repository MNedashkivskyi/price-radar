"""Lazy-singleton Playwright browser pool for headless page rendering.

Manages a single reusable Chromium browser instance with anti-detection
configuration.  The browser is created lazily on first ``get_page()`` call
and stays alive until ``shutdown()`` is called (or process exit).

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
import random
import threading
from contextlib import contextmanager
from typing import Generator

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

logger = logging.getLogger(__name__)

# Pool of real Chrome user-agent strings (rotated per browser context)
_USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
]

# Init script injected into every page to hide automation markers
_STEALTH_SCRIPT = """
// Remove navigator.webdriver flag
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});

// Override permissions query
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) =>
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters);

// Mask chrome runtime
window.chrome = {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {},
};

// Mask plugins length
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});

// Mask languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
});
"""


class BrowserPool:
    """Thread-safe lazy-singleton managing a Playwright Chromium browser.

    Anti-detection features:
    - Randomised real Chrome User-Agent per context
    - ``navigator.webdriver`` removed via init script
    - ``--disable-blink-features=AutomationControlled``
    - Standard viewport (1920x1080), locale, timezone
    - Chrome runtime stubs injected

    Concurrency:
    - A ``threading.Semaphore`` limits the number of pages open at once
      (default 3) to avoid resource exhaustion.
    """

    _lock = threading.Lock()
    _playwright: Playwright | None = None
    _browser: Browser | None = None
    _initialised = False
    _max_pages = 3
    _semaphore = threading.Semaphore(_max_pages)

    # ── Lifecycle ────────────────────────────────────────────────────

    @classmethod
    def _ensure_browser(cls) -> Browser:
        """Lazily launch the Chromium browser (double-checked locking)."""
        if cls._browser is not None:
            return cls._browser

        with cls._lock:
            if cls._browser is not None:
                return cls._browser

            logger.info("BrowserPool: launching Chromium (headless)...")
            cls._playwright = sync_playwright().start()
            cls._browser = cls._playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-setuid-sandbox",
                ],
            )
            cls._initialised = True
            atexit.register(cls.shutdown)
            logger.info("BrowserPool: Chromium ready")
            return cls._browser

    @classmethod
    def shutdown(cls) -> None:
        """Close the browser and Playwright.  Safe to call multiple times."""
        with cls._lock:
            if cls._browser is not None:
                try:
                    cls._browser.close()
                except Exception:
                    pass
                cls._browser = None

            if cls._playwright is not None:
                try:
                    cls._playwright.stop()
                except Exception:
                    pass
                cls._playwright = None

            cls._initialised = False
            logger.info("BrowserPool: shutdown complete")

    # ── Page Management ──────────────────────────────────────────────

    @classmethod
    @contextmanager
    def get_page(
        cls,
        *,
        timeout: int = 60_000,
        proxy_server: str | None = None,
    ) -> Generator[Page, None, None]:
        """Yield a fresh Playwright ``Page`` inside a new browser context.

        The context (and page) are destroyed when the context-manager exits.
        A semaphore limits the number of concurrent pages.

        Args:
            timeout: Default navigation timeout in milliseconds.
            proxy_server: Optional proxy URL for routing requests through
                a proxy (e.g. ``http://user:pass@gate.smartproxy.com:10001``).
                Playwright passes this to the browser context.
        """
        cls._semaphore.acquire()
        context: BrowserContext | None = None
        try:
            browser = cls._ensure_browser()
            ua = random.choice(_USER_AGENTS)
            context_kwargs: dict = {
                "user_agent": ua,
                "viewport": {"width": 1920, "height": 1080},
                "locale": "en-US",
                "timezone_id": "America/New_York",
                "java_script_enabled": True,
                "ignore_https_errors": True,
            }
            if proxy_server:
                context_kwargs["proxy"] = {"server": proxy_server}

            context = browser.new_context(**context_kwargs)
            context.add_init_script(_STEALTH_SCRIPT)
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
