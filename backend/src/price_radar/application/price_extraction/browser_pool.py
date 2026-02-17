"""Lazy-singleton Playwright browser pool for headless page rendering.

Manages a single reusable Chromium browser instance with advanced
anti-detection configuration.  The browser is created lazily on first
``get_page()`` call and stays alive until ``shutdown()`` is called
(or process exit).

Anti-detection uses ``playwright-stealth`` plus additional hardening
to bypass PerimeterX, Akamai, DataDome, and Cloudflare Turnstile.

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
from playwright_stealth import Stealth

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

# Additional stealth script beyond playwright-stealth defaults.
# Patches signals that advanced bot detectors check.
_EXTRA_STEALTH_SCRIPT = """
// ── navigator.connection (Network Information API) ────────────────
Object.defineProperty(navigator, 'connection', {
    get: () => ({
        downlink: 10,
        effectiveType: '4g',
        rtt: 50,
        saveData: false,
    }),
});

// ── window.outerWidth / outerHeight match inner (non-headless) ───
Object.defineProperty(window, 'outerWidth', {
    get: () => window.innerWidth,
});
Object.defineProperty(window, 'outerHeight', {
    get: () => window.innerHeight + 85,  // Chrome toolbar height
});

// ── Notification API (not available in headless by default) ──────
if (!window.Notification) {
    window.Notification = {
        permission: 'default',
        requestPermission: () => Promise.resolve('default'),
    };
}

// ── screen properties (headless default is 0x0) ─────────────────
Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
Object.defineProperty(screen, 'pixelDepth', { get: () => 24 });

// ── Media devices (headless usually has none) ────────────────────
if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
    const original = navigator.mediaDevices.enumerateDevices.bind(
        navigator.mediaDevices
    );
    navigator.mediaDevices.enumerateDevices = () =>
        original().then((devices) =>
            devices.length > 0
                ? devices
                : [
                      { deviceId: 'default', kind: 'audioinput',
                        label: 'Default', groupId: 'default' },
                      { deviceId: 'default', kind: 'videoinput',
                        label: 'Default', groupId: 'default' },
                  ]
        );
}

// ── Mask automation-related objects ──────────────────────────────
delete window.__playwright;
delete window.__pw_manual;
"""


class BrowserPool:
    """Thread-safe lazy-singleton managing a Playwright Chromium browser.

    Anti-detection features:
    - **playwright-stealth** patches (WebGL, canvas, webdriver, chrome
      runtime, permissions, plugins, languages, iframe, codecs, etc.)
    - Extra hardening: navigator.connection, outerWidth/Height,
      Notification API, screen properties, media devices
    - Randomised real Chrome User-Agent per context
    - Slightly randomised viewport to avoid fingerprint clustering
    - ``--disable-blink-features=AutomationControlled``
    - US locale and timezone

    Concurrency:
    - A ``threading.Semaphore`` limits the number of pages open at once
      (default 3) to avoid resource exhaustion.

    Proxy support:
    - Pass ``proxy_server`` to ``get_page()`` to route through a proxy.
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
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-setuid-sandbox",
                    "--disable-web-security",
                    "--disable-infobars",
                    "--window-size=1920,1080",
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
            proxy_server: Optional proxy URL (``http://user:pass@host:port``).
        """
        cls._semaphore.acquire()
        context: BrowserContext | None = None
        try:
            browser = cls._ensure_browser()
            ua = random.choice(_USER_AGENTS)

            # Slight viewport randomisation to avoid fingerprint clustering
            vp_w = 1920 + random.randint(-20, 20)
            vp_h = 1080 + random.randint(-20, 20)

            context_kwargs: dict = {
                "user_agent": ua,
                "viewport": {"width": vp_w, "height": vp_h},
                "locale": "en-US",
                "timezone_id": "America/New_York",
                "java_script_enabled": True,
                "ignore_https_errors": True,
                "color_scheme": "light",
            }

            if proxy_server:
                context_kwargs["proxy"] = {"server": proxy_server}

            context = browser.new_context(**context_kwargs)
            context.add_init_script(_EXTRA_STEALTH_SCRIPT)
            page = context.new_page()

            # Apply playwright-stealth patches (WebGL, canvas, webdriver, etc.)
            _stealth = Stealth(
                chrome_runtime=True,  # enable chrome.runtime stub
                navigator_languages_override=("en-US", "en"),
                navigator_platform_override="Win32",
            )
            _stealth.apply_stealth_sync(page)

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
