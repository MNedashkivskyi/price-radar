"""Round-robin proxy rotator with failure tracking.

Rotates through a list of proxy URLs for both httpx and Playwright
requests.  Proxies that fail are deprioritised (moved to the back of
the queue) but not permanently removed.

Usage::

    rotator = ProxyRotator("http://p1:8080,http://p2:8080")
    proxy = rotator.next()        # "http://p1:8080"
    rotator.report_failure(proxy)  # deprioritise p1
    proxy = rotator.next()        # "http://p2:8080"
"""

from __future__ import annotations

import logging
import threading
from collections import deque

logger = logging.getLogger(__name__)


class ProxyRotator:
    """Thread-safe round-robin proxy rotator with failure deprioritisation.

    Args:
        proxy_list: Comma-separated proxy URLs, or an iterable of URLs.
            Each URL should be in the format ``http://user:pass@host:port``.
    """

    def __init__(self, proxy_list: str | list[str]) -> None:
        if isinstance(proxy_list, str):
            proxies = [p.strip() for p in proxy_list.split(",") if p.strip()]
        else:
            proxies = list(proxy_list)

        self._proxies: deque[str] = deque(proxies)
        self._lock = threading.Lock()
        self._failures: dict[str, int] = {}

    @property
    def available(self) -> bool:
        """True if at least one proxy is configured."""
        return len(self._proxies) > 0

    def next(self) -> str | None:
        """Return the next proxy URL (round-robin), or None if empty."""
        with self._lock:
            if not self._proxies:
                return None
            proxy = self._proxies[0]
            self._proxies.rotate(-1)
            return proxy

    def report_failure(self, proxy: str) -> None:
        """Record a failure for a proxy (moves it to back of queue)."""
        with self._lock:
            self._failures[proxy] = self._failures.get(proxy, 0) + 1
            # Move the failed proxy to the back
            try:
                self._proxies.remove(proxy)
                self._proxies.append(proxy)
            except ValueError:
                pass
            logger.debug(
                "Proxy failure recorded: %s (total: %d)",
                proxy, self._failures[proxy],
            )

    def report_success(self, proxy: str) -> None:
        """Reset failure count for a proxy on success."""
        with self._lock:
            self._failures.pop(proxy, None)

    def get_failure_count(self, proxy: str) -> int:
        """Return the number of consecutive failures for a proxy."""
        return self._failures.get(proxy, 0)

    def __len__(self) -> int:
        return len(self._proxies)

    def __repr__(self) -> str:
        return f"ProxyRotator({len(self._proxies)} proxies)"
