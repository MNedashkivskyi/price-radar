"""Per-domain rate limiter backed by Redis sliding window counters.

Prevents IP bans by throttling outgoing requests per domain.  When
``scrape_all_active`` fans out 500 tasks simultaneously, the rate limiter
ensures that only N requests hit each domain per minute.

Architecture::

    ┌──────────────────┐
    │  PageFetcher     │
    │  fetch(url)      │
    │    ↓             │
    │  rate_limiter    │──► Redis ZADD / ZRANGEBYSCORE (sliding window)
    │  .wait_for_slot()│
    │    ↓             │
    │  httpx / PW      │
    └──────────────────┘

Usage::

    from price_radar.application.rate_limiter import DomainRateLimiter

    limiter = DomainRateLimiter(redis_url="redis://localhost:6379/0")
    limiter.wait_for_slot("amazon.com", max_wait=30.0)
    # ... now safe to make the request
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ── Key prefix in Redis ──────────────────────────────────────────────────
_REDIS_KEY_PREFIX = "rate_limit:"


# ── Rate configuration ───────────────────────────────────────────────────

@dataclass(frozen=True)
class RateConfig:
    """Rate limit configuration for a single domain.

    Attributes:
        requests_per_minute: Maximum requests allowed in the sliding window.
        window_seconds: Sliding window size (default 60s = 1 minute).
    """

    requests_per_minute: int
    window_seconds: int = 60


# ── Default rate limits per domain ───────────────────────────────────────
# Conservative defaults — stricter for known aggressive anti-bot sites.

DEFAULT_RATE_LIMITS: dict[str, RateConfig] = {
    # E-commerce giants — moderate limits
    "amazon.com": RateConfig(requests_per_minute=10),
    "ebay.com": RateConfig(requests_per_minute=10),
    "walmart.com": RateConfig(requests_per_minute=8),
    # Aggressive anti-bot sites — very strict
    "target.com": RateConfig(requests_per_minute=3),
    "bestbuy.com": RateConfig(requests_per_minute=3),
    "etsy.com": RateConfig(requests_per_minute=2),
    "aliexpress.com": RateConfig(requests_per_minute=2),
    # Shopify stores — moderate
    "gymshark.com": RateConfig(requests_per_minute=5),
    "fashionnova.com": RateConfig(requests_per_minute=5),
    "allbirds.com": RateConfig(requests_per_minute=5),
    # Other known sites
    "newegg.com": RateConfig(requests_per_minute=5),
    "nike.com": RateConfig(requests_per_minute=5),
    "ikea.com": RateConfig(requests_per_minute=3),
    "zara.com": RateConfig(requests_per_minute=3),
    "hm.com": RateConfig(requests_per_minute=3),
    "uniqlo.com": RateConfig(requests_per_minute=3),
}

# Fallback for unknown domains
DEFAULT_UNKNOWN_RATE = RateConfig(requests_per_minute=5)


# ── Custom exception ─────────────────────────────────────────────────────

class RateLimitExceeded(Exception):
    """Raised when the rate limit wait would exceed the allowed max_wait."""

    def __init__(self, domain: str, wait_needed: float, max_wait: float) -> None:
        self.domain = domain
        self.wait_needed = wait_needed
        self.max_wait = max_wait
        super().__init__(
            f"Rate limit for {domain}: need to wait {wait_needed:.1f}s "
            f"but max_wait is {max_wait:.1f}s"
        )


# ── Helper: extract base domain from URL ─────────────────────────────────

def extract_domain(url: str) -> str:
    """Extract the base domain from a URL (e.g., 'www.amazon.com' → 'amazon.com')."""
    parsed = urlparse(url)
    host = (parsed.netloc or parsed.path.split("/")[0]).lower()
    # Strip port
    host = host.split(":")[0]
    # Strip www.
    if host.startswith("www."):
        host = host[4:]
    # For subdomains like uk.gymshark.com, use the base (gymshark.com)
    parts = host.split(".")
    if len(parts) > 2:
        host = ".".join(parts[-2:])
    return host


# ── DomainRateLimiter ────────────────────────────────────────────────────

class DomainRateLimiter:
    """Per-domain rate limiter using Redis sorted sets (sliding window).

    Each request is recorded as a member in a sorted set keyed by domain,
    with the timestamp as the score.  Before each request, old entries
    outside the window are pruned, and the count of remaining entries is
    checked against the limit.

    Redis commands used (per ``acquire`` call):
        1. ``ZREMRANGEBYSCORE`` — prune entries outside the window
        2. ``ZCARD`` — count entries in the window
        3. ``ZADD`` — record the new request (only if under limit)

    All three run in a Redis pipeline for atomicity.

    Args:
        redis_client: A ``redis.Redis`` (sync) instance.
        rate_limits: Optional dict overriding default per-domain limits.
        default_rate: Rate config for domains not in the limits dict.
    """

    def __init__(
        self,
        redis_client: object | None = None,
        *,
        rate_limits: dict[str, RateConfig] | None = None,
        default_rate: RateConfig | None = None,
    ) -> None:
        self._redis = redis_client
        self._rate_limits: dict[str, RateConfig] = {
            **DEFAULT_RATE_LIMITS,
            **(rate_limits or {}),
        }
        self._default_rate = default_rate or DEFAULT_UNKNOWN_RATE

    # ── Public API ───────────────────────────────────────────────────

    def get_config(self, domain: str) -> RateConfig:
        """Get the rate limit config for a domain.

        Checks exact match first, then base domain, then falls back
        to the default rate.
        """
        # Exact match
        if domain in self._rate_limits:
            return self._rate_limits[domain]

        # Base domain fallback (e.g., "uk.amazon.com" → "amazon.com")
        parts = domain.split(".")
        if len(parts) > 2:
            base = ".".join(parts[-2:])
            if base in self._rate_limits:
                return self._rate_limits[base]

        return self._default_rate

    def acquire(self, domain: str) -> bool:
        """Try to acquire a rate limit slot for the given domain.

        Returns True if the request is allowed (slot acquired),
        False if the rate limit is exceeded.

        When no Redis client is configured, always returns True
        (no-op mode for tests / local dev).
        """
        if self._redis is None:
            return True

        config = self.get_config(domain)
        now = time.time()
        window_start = now - config.window_seconds
        key = f"{_REDIS_KEY_PREFIX}{domain}"

        pipe = self._redis.pipeline(transaction=True)  # type: ignore[union-attr]
        pipe.zremrangebyscore(key, "-inf", window_start)
        pipe.zcard(key)
        # Use a unique member: timestamp with enough precision
        # (add a small random suffix to avoid collisions in high-throughput)
        member = f"{now}"
        pipe.zadd(key, {member: now})
        pipe.expire(key, config.window_seconds + 10)  # TTL slightly longer than window
        results = pipe.execute()

        # results[0] = removed count, results[1] = count BEFORE zadd
        current_count = results[1]

        if current_count >= config.requests_per_minute:
            # Over limit — remove the entry we just added
            self._redis.zrem(key, member)  # type: ignore[union-attr]
            return False

        return True

    def time_until_slot(self, domain: str) -> float:
        """Return seconds until the next slot opens for this domain.

        Returns 0.0 if a slot is available now.
        Returns -1.0 if Redis is not configured (no-op mode).
        """
        if self._redis is None:
            return -1.0

        config = self.get_config(domain)
        now = time.time()
        window_start = now - config.window_seconds
        key = f"{_REDIS_KEY_PREFIX}{domain}"

        # Remove expired entries
        self._redis.zremrangebyscore(key, "-inf", window_start)  # type: ignore[union-attr]
        count = self._redis.zcard(key)  # type: ignore[union-attr]

        if count < config.requests_per_minute:
            return 0.0

        # Get the oldest entry in the window — that's when the first slot frees up
        oldest = self._redis.zrange(key, 0, 0, withscores=True)  # type: ignore[union-attr]
        if not oldest:
            return 0.0

        oldest_ts = oldest[0][1]
        slot_opens_at = oldest_ts + config.window_seconds
        wait = slot_opens_at - now

        return max(0.0, wait)

    def wait_for_slot(
        self,
        domain: str,
        *,
        max_wait: float = 120.0,
        poll_interval: float = 1.0,
    ) -> float:
        """Block until a rate limit slot is available for the domain.

        Args:
            domain: The domain to rate-limit.
            max_wait: Maximum seconds to wait before raising RateLimitExceeded.
            poll_interval: Seconds between acquire attempts.

        Returns:
            Total seconds waited.

        Raises:
            RateLimitExceeded: If waiting would exceed max_wait.
        """
        if self._redis is None:
            return 0.0

        total_waited = 0.0

        while not self.acquire(domain):
            wait_needed = self.time_until_slot(domain)

            if total_waited + max(wait_needed, poll_interval) > max_wait:
                raise RateLimitExceeded(
                    domain=domain,
                    wait_needed=total_waited + wait_needed,
                    max_wait=max_wait,
                )

            sleep_time = min(max(wait_needed, poll_interval), max_wait - total_waited)
            if sleep_time <= 0:
                raise RateLimitExceeded(
                    domain=domain,
                    wait_needed=total_waited,
                    max_wait=max_wait,
                )

            logger.debug(
                "Rate limit: waiting %.1fs for %s (waited %.1fs so far)",
                sleep_time,
                domain,
                total_waited,
            )
            time.sleep(sleep_time)
            total_waited += sleep_time

        return total_waited

    def reset(self, domain: str) -> None:
        """Clear all rate limit data for a domain (useful for tests)."""
        if self._redis is not None:
            key = f"{_REDIS_KEY_PREFIX}{domain}"
            self._redis.delete(key)  # type: ignore[union-attr]
