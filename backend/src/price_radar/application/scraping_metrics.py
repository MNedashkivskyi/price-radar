"""Scraping metrics — Redis counters for monitoring scraping health.

Tracks per-domain, per-day statistics using Redis hashes with TTL.
Data auto-expires after 30 days so no manual cleanup is needed.

Redis key patterns::

    scrape:stats:{domain}:{YYYY-MM-DD}  →  hash {
        "success":       "142",
        "failure":       "8",
        "method:httpx":  "120",
        "method:camoufox": "22",
        "method:none":   "8",
        "total_fetch_time": "456.78",   # cumulative seconds
        "error:timeout": "3",
        "error:extraction_failed": "5",
    }

    scrape:domains  →  set of all tracked domain names (no TTL, pruned lazily)

Usage::

    from price_radar.application.scraping_metrics import ScrapingMetrics

    metrics = ScrapingMetrics(redis_client)
    metrics.record_scrape("amazon.com", success=True, fetch_method="httpx",
                          fetch_time=1.23)
    summary = metrics.get_domain_stats("amazon.com", days=1)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# ── Redis key helpers ────────────────────────────────────────────────────

_STATS_PREFIX = "scrape:stats:"
_DOMAINS_KEY = "scrape:domains"
_STATS_TTL_SECONDS = 30 * 86400  # 30 days


def _stats_key(domain: str, day: date) -> str:
    """Build the Redis hash key for a domain on a given day."""
    return f"{_STATS_PREFIX}{domain}:{day.isoformat()}"


def _today() -> date:
    return datetime.now(timezone.utc).date()


# ── Data classes ─────────────────────────────────────────────────────────


@dataclass
class DomainDayStats:
    """Aggregated stats for one domain on one day."""

    domain: str
    day: date
    success: int = 0
    failure: int = 0
    method_httpx: int = 0
    method_camoufox: int = 0
    method_none: int = 0
    total_fetch_time: float = 0.0
    errors: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.success + self.failure

    @property
    def success_rate(self) -> float:
        return (self.success / self.total * 100.0) if self.total > 0 else 0.0

    @property
    def avg_fetch_time(self) -> float:
        return (self.total_fetch_time / self.total) if self.total > 0 else 0.0


@dataclass
class DomainSummary:
    """Multi-day aggregated stats for a domain."""

    domain: str
    days: int
    success: int = 0
    failure: int = 0
    method_httpx: int = 0
    method_camoufox: int = 0
    method_none: int = 0
    total_fetch_time: float = 0.0
    errors: dict[str, int] = field(default_factory=dict)
    last_success_at: float | None = None

    @property
    def total(self) -> int:
        return self.success + self.failure

    @property
    def success_rate(self) -> float:
        return (self.success / self.total * 100.0) if self.total > 0 else 0.0

    @property
    def avg_fetch_time(self) -> float:
        return (self.total_fetch_time / self.total) if self.total > 0 else 0.0


@dataclass
class HealthSummary:
    """Overall scraping health snapshot."""

    total_scrapes_24h: int = 0
    success_24h: int = 0
    failure_24h: int = 0
    success_rate_24h: float = 0.0
    active_domains: int = 0
    domains_below_threshold: list[str] = field(default_factory=list)
    queue_depth: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class FailureGroup:
    """Failures grouped by error type and domain."""

    error_type: str
    domain: str
    count: int
    last_seen: str  # ISO date string


# ── ScrapingMetrics ──────────────────────────────────────────────────────


class ScrapingMetrics:
    """Redis-backed scraping metrics collector and aggregator.

    Args:
        redis_client: A ``redis.Redis`` (sync) instance.  When ``None``,
            all operations are no-ops (for tests / local dev without Redis).
    """

    def __init__(self, redis_client: object | None = None) -> None:
        self._redis = redis_client

    # ── Recording ─────────────────────────────────────────────────────

    def record_scrape(
        self,
        domain: str,
        *,
        success: bool,
        fetch_method: str = "none",
        fetch_time: float = 0.0,
        error: str | None = None,
    ) -> None:
        """Record the outcome of a single scrape attempt.

        Increments the appropriate counters in the per-domain, per-day
        Redis hash.  Also tracks the domain name in a global set.

        Args:
            domain: Base domain (e.g. ``"amazon.com"``).
            success: Whether the scrape succeeded.
            fetch_method: ``"httpx"``, ``"camoufox"``, or ``"none"``.
            fetch_time: Seconds taken for the fetch phase.
            error: Error type string when ``success=False`` (e.g.
                ``"timeout"``, ``"extraction_failed"``).
        """
        if self._redis is None:
            return

        today = _today()
        key = _stats_key(domain, today)

        pipe = self._redis.pipeline()  # type: ignore[union-attr]

        # Success / failure count
        if success:
            pipe.hincrby(key, "success", 1)
            pipe.hset(key, "last_success_at", str(time.time()))
        else:
            pipe.hincrby(key, "failure", 1)

        # Fetch method distribution
        method_key = f"method:{fetch_method}" if fetch_method else "method:none"
        pipe.hincrby(key, method_key, 1)

        # Cumulative fetch time (for avg calculation)
        pipe.hincrbyfloat(key, "total_fetch_time", round(fetch_time, 3))

        # Error type breakdown
        if error and not success:
            # Normalise error key: take the first part before ':'
            err_key = f"error:{error.split(':')[0].strip()}"
            pipe.hincrby(key, err_key, 1)

        # Set TTL (idempotent — resets on each write, which is fine)
        pipe.expire(key, _STATS_TTL_SECONDS)

        # Track domain in global set
        pipe.sadd(_DOMAINS_KEY, domain)  # type: ignore[union-attr]

        pipe.execute()

    # ── Querying ──────────────────────────────────────────────────────

    def get_tracked_domains(self) -> list[str]:
        """Return all domain names that have ever been tracked."""
        if self._redis is None:
            return []
        members = self._redis.smembers(_DOMAINS_KEY)  # type: ignore[union-attr]
        return sorted(
            m if isinstance(m, str) else m.decode() for m in members
        )

    def get_domain_day_stats(self, domain: str, day: date) -> DomainDayStats:
        """Read the stats hash for a domain on a specific day."""
        stats = DomainDayStats(domain=domain, day=day)
        if self._redis is None:
            return stats

        key = _stats_key(domain, day)
        raw = self._redis.hgetall(key)  # type: ignore[union-attr]
        if not raw:
            return stats

        # Decode if needed
        data: dict[str, str] = {}
        for k, v in raw.items():
            dk = k if isinstance(k, str) else k.decode()
            dv = v if isinstance(v, str) else v.decode()
            data[dk] = dv

        stats.success = int(data.get("success", "0"))
        stats.failure = int(data.get("failure", "0"))
        stats.method_httpx = int(data.get("method:httpx", "0"))
        stats.method_camoufox = int(data.get("method:camoufox", "0"))
        stats.method_none = int(data.get("method:none", "0"))
        stats.total_fetch_time = float(data.get("total_fetch_time", "0.0"))

        # Collect error: prefixed fields
        for k, v in data.items():
            if k.startswith("error:"):
                err_type = k[6:]  # strip "error:" prefix
                stats.errors[err_type] = int(v)

        return stats

    def get_domain_stats(self, domain: str, *, days: int = 1) -> DomainSummary:
        """Aggregate stats for a domain over the last N days."""
        summary = DomainSummary(domain=domain, days=days)
        if self._redis is None:
            return summary

        today = _today()
        for i in range(days):
            day = today - timedelta(days=i)
            day_stats = self.get_domain_day_stats(domain, day)
            summary.success += day_stats.success
            summary.failure += day_stats.failure
            summary.method_httpx += day_stats.method_httpx
            summary.method_camoufox += day_stats.method_camoufox
            summary.method_none += day_stats.method_none
            summary.total_fetch_time += day_stats.total_fetch_time
            for err, count in day_stats.errors.items():
                summary.errors[err] = summary.errors.get(err, 0) + count

        # Get last_success_at from today's hash
        today_key = _stats_key(domain, today)
        raw_ts = self._redis.hget(today_key, "last_success_at")  # type: ignore[union-attr]
        if raw_ts is not None:
            try:
                summary.last_success_at = float(raw_ts)
            except (TypeError, ValueError):
                pass

        return summary

    def get_health_summary(
        self,
        *,
        alert_threshold: float = 50.0,
        queue_depth: int = 0,
    ) -> HealthSummary:
        """Build an overall health snapshot for the last 24 hours.

        Args:
            alert_threshold: Success rate (%) below which a domain is
                considered unhealthy.
            queue_depth: Current Celery queue depth (passed in by the caller
                since it requires Celery broker inspection).
        """
        health = HealthSummary(queue_depth=queue_depth)

        domains = self.get_tracked_domains()
        health.active_domains = len(domains)

        for domain in domains:
            stats = self.get_domain_stats(domain, days=1)
            health.total_scrapes_24h += stats.total
            health.success_24h += stats.success
            health.failure_24h += stats.failure
            if stats.total > 0 and stats.success_rate < alert_threshold:
                health.domains_below_threshold.append(domain)

        if health.total_scrapes_24h > 0:
            health.success_rate_24h = round(
                health.success_24h / health.total_scrapes_24h * 100.0, 2
            )

        return health

    def get_failure_groups(self, *, days: int = 1) -> list[FailureGroup]:
        """Return recent failures grouped by error type and domain.

        Args:
            days: Number of days to look back (default 1).

        Returns:
            Sorted list of failure groups (highest count first).
        """
        if self._redis is None:
            return []

        groups: dict[tuple[str, str], int] = {}
        domains = self.get_tracked_domains()
        today = _today()

        for domain in domains:
            for i in range(days):
                day = today - timedelta(days=i)
                day_stats = self.get_domain_day_stats(domain, day)
                for err_type, count in day_stats.errors.items():
                    key = (err_type, domain)
                    groups[key] = groups.get(key, 0) + count

        result = [
            FailureGroup(
                error_type=err_type,
                domain=domain,
                count=count,
                last_seen=today.isoformat(),
            )
            for (err_type, domain), count in groups.items()
        ]
        result.sort(key=lambda g: g.count, reverse=True)
        return result
