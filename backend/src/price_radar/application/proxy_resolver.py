"""Proxy resolver — determines per-domain whether to use direct or residential proxy.

The ``ProxyResolver`` maintains a per-domain classification of which proxy
tier should be used.  Known hard domains (Allegro, Amazon, Zalando, etc.)
are pre-configured to always use a residential proxy.  Unknown domains
default to direct connection; if a direct request fails with 403/429, the
resolver automatically escalates to the residential proxy on retry.

**Proxy pool rotation**: the resolver accepts a *list* of residential
proxy endpoints and rotates across them in round-robin fashion.  This
spreads traffic evenly across gateway nodes, improves throughput, and
reduces per-endpoint rate-limit pressure.

Domain classifications are cached in Redis (with a 7-day TTL) to avoid
repeated discovery.  When no Redis client is provided, classification is
held in-process memory only.

Proxy credentials are read from environment variables — never hardcoded.

Usage::

    from price_radar.application.proxy_resolver import ProxyResolver, ProxyTier

    # Single proxy (backward compatible):
    resolver = ProxyResolver(
        proxy_url="http://user:pass@gate.smartproxy.com:10001",
        redis_client=redis_client,
    )

    # Multiple proxy endpoints (round-robin rotation):
    resolver = ProxyResolver(
        proxy_urls=[
            "http://user:pass@gate.smartproxy.com:10001",
            "http://user:pass@gate.smartproxy.com:10002",
            ...
        ],
        redis_client=redis_client,
    )

    tier = resolver.resolve("amazon.com")     # → ProxyTier.RESIDENTIAL
    tier = resolver.resolve("example.com")    # → ProxyTier.DIRECT

    url = resolver.get_proxy_url("amazon.com")  # → "http://user:pass@...:<port>"
    url = resolver.get_proxy_url("example.com") # → None (direct)

    # After a 403/429 on direct:
    resolver.escalate("example.com")
    tier = resolver.resolve("example.com")    # → ProxyTier.RESIDENTIAL
"""

from __future__ import annotations

import itertools
import logging
import threading
import time
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── Proxy tier enum ──────────────────────────────────────────────────────


class ProxyTier(str, Enum):
    """Proxy routing tier for a domain."""

    DIRECT = "direct"
    RESIDENTIAL = "residential"


# ── Domains known to require residential proxies ─────────────────────────

# These domains aggressively block datacenter IPs (403, CAPTCHA, geo-fence).
# They are pre-classified as RESIDENTIAL and never attempted via DIRECT.
_KNOWN_RESIDENTIAL_DOMAINS: frozenset[str] = frozenset({
    # Marketplaces — aggressive anti-bot
    "allegro.pl",
    "amazon.com",
    "amazon.co.uk",
    "amazon.de",
    "amazon.fr",
    "amazon.es",
    "amazon.it",
    "amazon.co.jp",
    "amazon.ca",
    "zalando.pl",
    "zalando.de",
    "zalando.co.uk",
    "zalando.fr",
    "ceneo.pl",
    # Retailers — Cloudflare / PerimeterX protected
    "nike.com",
    "adidas.com",
    "footlocker.com",
    "finishline.com",
    "target.com",
    "bestbuy.com",
    "homedepot.com",
    "lowes.com",
    "wayfair.com",
    "nordstrom.com",
    "macys.com",
    "sephora.com",
    "ulta.com",
    "overstock.com",
    "bathandbodyworks.com",
    "rei.com",
    "dickssportinggoods.com",
    "iherb.com",
    # Fashion
    "zara.com",
    "hm.com",
    "uniqlo.com",
    "asos.com",
    "fashionnova.com",
    # Home / specialty
    "etsy.com",
    "barnesandnoble.com",
    "cb2.com",
    "vitacost.com",
    "buybuybaby.com",
    # Tech / electronics
    "newegg.com",
    "bhphotovideo.com",
})

# Redis key patterns
_REDIS_PREFIX = "proxy:tier:"
_REDIS_TTL_SECONDS = 7 * 86400  # 7 days


class ProxyResolver:
    """Resolves per-domain proxy routing with Redis-backed caching.

    Supports a **pool** of residential proxy endpoints.  When multiple
    URLs are provided, the resolver rotates across them in thread-safe
    round-robin order.  This spreads traffic evenly across Decodo
    gateway nodes and avoids per-endpoint rate limits.

    Args:
        proxy_url: Single Decodo/Smartproxy residential proxy URL
            (backward compatible).  Ignored when ``proxy_urls`` is
            provided.
        proxy_urls: List of residential proxy URLs to rotate across.
            Takes precedence over ``proxy_url``.  Empty entries are
            silently filtered out.
        redis_client: Optional sync Redis client for caching domain
            classifications.  Without it, classification lives only in
            process memory.
    """

    def __init__(
        self,
        *,
        proxy_url: str = "",
        proxy_urls: list[str] | None = None,
        redis_client: object | None = None,
    ) -> None:
        # Build the proxy pool — proxy_urls takes precedence over proxy_url
        if proxy_urls:
            self._proxy_pool: list[str] = [u for u in proxy_urls if u]
        elif proxy_url:
            self._proxy_pool = [proxy_url]
        else:
            self._proxy_pool = []

        # Thread-safe round-robin iterator over the pool
        self._pool_cycle = itertools.cycle(self._proxy_pool) if self._proxy_pool else None
        self._pool_lock = threading.Lock()

        # Keep a single-URL accessor for backward compat in tests
        self._proxy_url = self._proxy_pool[0] if self._proxy_pool else ""

        self._redis = redis_client
        # In-memory fallback cache (also used as read-through)
        self._memory_cache: dict[str, tuple[ProxyTier, float]] = {}

    # ── Public API ───────────────────────────────────────────────────

    @property
    def has_proxy(self) -> bool:
        """Return True if at least one residential proxy URL is configured."""
        return len(self._proxy_pool) > 0

    @property
    def pool_size(self) -> int:
        """Return the number of proxy endpoints in the pool."""
        return len(self._proxy_pool)

    def _next_proxy_url(self) -> str:
        """Return the next proxy URL from the round-robin pool.

        Thread-safe: uses a lock around the ``itertools.cycle`` iterator
        so concurrent Celery workers get evenly distributed endpoints.
        """
        if not self._pool_cycle:
            return ""
        with self._pool_lock:
            return next(self._pool_cycle)

    def resolve(self, domain: str) -> ProxyTier:
        """Determine which proxy tier to use for a domain.

        Resolution order:
        1. Known residential domains → RESIDENTIAL
        2. Redis cache (if available) → cached tier
        3. In-memory cache → cached tier
        4. Default → DIRECT
        """
        base = self._base_domain(domain)

        # 1. Hard-coded known residential domains
        if base in _KNOWN_RESIDENTIAL_DOMAINS:
            return ProxyTier.RESIDENTIAL

        # 2. Redis cache
        cached = self._read_cache(base)
        if cached is not None:
            return cached

        # 3. Default: direct
        return ProxyTier.DIRECT

    def get_proxy_url(self, domain: str) -> str | None:
        """Return a proxy URL for a domain, or None for DIRECT.

        When multiple proxy endpoints are configured, each call returns
        the **next** URL in round-robin order.  This distributes traffic
        evenly across the pool.

        Returns None when:
        - The domain resolves to DIRECT
        - No proxy URLs are configured
        """
        tier = self.resolve(domain)
        if tier == ProxyTier.RESIDENTIAL and self._proxy_pool:
            return self._next_proxy_url()
        return None

    def escalate(self, domain: str) -> None:
        """Escalate a domain from DIRECT to RESIDENTIAL.

        Called after a direct request fails with 403/429.  The escalation
        is cached in Redis (7 days) and in-memory.
        """
        base = self._base_domain(domain)

        # Don't escalate already-known domains (they're permanent)
        if base in _KNOWN_RESIDENTIAL_DOMAINS:
            return

        logger.info("Escalating domain to RESIDENTIAL proxy: %s", base)
        self._write_cache(base, ProxyTier.RESIDENTIAL)

    def reset(self, domain: str) -> None:
        """Reset a domain back to DIRECT (e.g. after successful direct fetch).

        Useful for periodic re-classification (domains older than 7 days
        auto-expire from Redis cache anyway).
        """
        base = self._base_domain(domain)
        if base in _KNOWN_RESIDENTIAL_DOMAINS:
            return  # Can't reset hard-coded domains
        self._write_cache(base, ProxyTier.DIRECT)

    def get_tier_info(self, domain: str) -> dict[str, str]:
        """Return debug info about a domain's proxy classification."""
        base = self._base_domain(domain)
        tier = self.resolve(domain)
        source = "default"

        if base in _KNOWN_RESIDENTIAL_DOMAINS:
            source = "known_residential"
        elif self._read_cache(base) is not None:
            source = "cached"

        return {
            "domain": base,
            "tier": tier.value,
            "source": source,
            "proxy_configured": str(self.has_proxy),
        }

    # ── Cache helpers ────────────────────────────────────────────────

    def _read_cache(self, base_domain: str) -> ProxyTier | None:
        """Read tier from Redis (primary) or memory (fallback)."""
        # Redis first
        if self._redis is not None:
            try:
                key = f"{_REDIS_PREFIX}{base_domain}"
                val = self._redis.get(key)  # type: ignore[union-attr]
                if val is not None:
                    tier_str = val if isinstance(val, str) else val.decode()
                    tier = ProxyTier(tier_str)
                    # Populate memory cache
                    self._memory_cache[base_domain] = (tier, time.time())
                    return tier
            except Exception:
                logger.debug("Redis read failed for proxy tier: %s", base_domain, exc_info=True)

        # Memory fallback
        entry = self._memory_cache.get(base_domain)
        if entry is not None:
            tier, cached_at = entry
            # Expire memory cache after 7 days too
            if time.time() - cached_at < _REDIS_TTL_SECONDS:
                return tier
            else:
                del self._memory_cache[base_domain]

        return None

    def _write_cache(self, base_domain: str, tier: ProxyTier) -> None:
        """Write tier to Redis and memory cache."""
        # Memory
        self._memory_cache[base_domain] = (tier, time.time())

        # Redis
        if self._redis is not None:
            try:
                key = f"{_REDIS_PREFIX}{base_domain}"
                self._redis.setex(key, _REDIS_TTL_SECONDS, tier.value)  # type: ignore[union-attr]
            except Exception:
                logger.debug("Redis write failed for proxy tier: %s", base_domain, exc_info=True)

    # ── Utilities ────────────────────────────────────────────────────

    @staticmethod
    def _base_domain(domain: str) -> str:
        """Normalise domain to base form (strip www., subdomain)."""
        d = domain.lower().replace("www.", "")
        parts = d.split(".")
        # Keep full domain for 2-part names (amazon.com)
        # and 3-part with country TLD (amazon.co.uk, allegro.pl)
        if len(parts) >= 3 and parts[-2] in ("co", "com"):
            return ".".join(parts[-3:])
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return d
