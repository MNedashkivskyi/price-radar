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
from urllib.parse import urlparse as _urlparse

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

# Init script injected into every page to hide automation markers.
# Covers signals checked by Cloudflare, PerimeterX, DataDome, and Akamai.
_STEALTH_SCRIPT = """
// ── 1. navigator.webdriver ───────────────────────────────────────
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
});

// ── 2. Permissions API ───────────────────────────────────────────
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) =>
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters);

// ── 3. Chrome runtime stubs ──────────────────────────────────────
window.chrome = {
    runtime: {
        connect: function() {},
        sendMessage: function() {},
        onMessage: { addListener: function() {} },
    },
    loadTimes: function() { return {}; },
    csi: function() { return {}; },
    app: { isInstalled: false, InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }, RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' } },
};

// ── 4. Plugins (real Chrome has 5 default plugins) ───────────────
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
            { name: 'Chromium PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: '' },
        ];
        plugins.length = 5;
        return plugins;
    },
});

// ── 5. Languages ─────────────────────────────────────────────────
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
});

// ── 6. WebGL renderer (hide SwiftShader / Google Inc. headless) ──
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    // UNMASKED_VENDOR_WEBGL = 37445, UNMASKED_RENDERER_WEBGL = 37446
    if (parameter === 37445) return 'Intel Inc.';
    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.call(this, parameter);
};
// Also cover WebGL2
if (typeof WebGL2RenderingContext !== 'undefined') {
    const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Intel Inc.';
        if (parameter === 37446) return 'Intel Iris OpenGL Engine';
        return getParameter2.call(this, parameter);
    };
}

// ── 7. window.outerWidth/Height matching inner (headless tells) ──
Object.defineProperty(window, 'outerWidth', { get: () => window.innerWidth });
Object.defineProperty(window, 'outerHeight', { get: () => window.innerHeight + 85 });  // 85 = typical Chrome toolbar

// ── 8. navigator.connection (missing in headless) ────────────────
if (!navigator.connection) {
    Object.defineProperty(navigator, 'connection', {
        get: () => ({
            effectiveType: '4g',
            rtt: 50,
            downlink: 10,
            saveData: false,
        }),
    });
}

// ── 9. Notification.permission ───────────────────────────────────
if (Notification.permission === 'denied') {
    Object.defineProperty(Notification, 'permission', { get: () => 'default' });
}

// ── 10. iframe contentWindow consistency ─────────────────────────
try {
    Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
        get: function() {
            return window;
        },
    });
} catch(e) {}

// ── 11. Mask automation-related properties ───────────────────────
delete navigator.__proto__.webdriver;
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
                    # Extra anti-detection args
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-site-isolation-trials",
                    "--disable-web-security",
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
        semaphore_timeout: float | None = None,
    ) -> Generator[Page, None, None]:
        """Yield a fresh Playwright ``Page`` inside a new browser context.

        The context (and page) are destroyed when the context-manager exits.
        A semaphore limits the number of concurrent pages.

        Args:
            timeout: Default navigation timeout in milliseconds.
            proxy_server: Optional proxy URL for routing requests through
                a proxy (e.g. ``http://user:pass@gate.smartproxy.com:10001``).
                Playwright passes this to the browser context.
            semaphore_timeout: Maximum seconds to wait for a semaphore slot.
                ``None`` means block indefinitely (legacy behaviour).
        Raises:
            TimeoutError: If *semaphore_timeout* expires before a slot opens.
        """
        if semaphore_timeout is not None:
            acquired = cls._semaphore.acquire(timeout=semaphore_timeout)
            if not acquired:
                raise TimeoutError(
                    f"BrowserPool: timed out waiting {semaphore_timeout:.1f}s "
                    "for a page slot"
                )
        else:
            cls._semaphore.acquire()
        context: BrowserContext | None = None
        try:
            browser = cls._ensure_browser()
            ua = random.choice(_USER_AGENTS)
            # Slight viewport jitter avoids fingerprint clustering
            vp_w = 1920 + random.randint(-20, 20)
            vp_h = 1080 + random.randint(-20, 20)
            context_kwargs: dict = {
                "user_agent": ua,
                "viewport": {"width": vp_w, "height": vp_h},
                "locale": "en-US",
                "timezone_id": "America/New_York",
                "java_script_enabled": True,
                "ignore_https_errors": True,
            }
            if proxy_server:
                # Playwright requires auth as separate fields, NOT embedded
                # in the URL.  Parse "http://user:pass@host:port" into
                # {"server": "http://host:port", "username": "user", "password": "pass"}
                parsed_proxy = _urlparse(proxy_server)
                proxy_dict: dict[str, str] = {
                    "server": (
                        f"{parsed_proxy.scheme}://"
                        f"{parsed_proxy.hostname}:{parsed_proxy.port}"
                    ),
                }
                if parsed_proxy.username:
                    proxy_dict["username"] = parsed_proxy.username
                if parsed_proxy.password:
                    proxy_dict["password"] = parsed_proxy.password
                context_kwargs["proxy"] = proxy_dict
                logger.debug(
                    "BrowserPool: using proxy %s://%s:%s (auth=%s)",
                    parsed_proxy.scheme,
                    parsed_proxy.hostname,
                    parsed_proxy.port,
                    bool(parsed_proxy.username),
                )

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
