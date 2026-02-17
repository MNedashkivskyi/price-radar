"""Tests for the monitoring dashboard — scraping metrics, API endpoints, alerts.

Tests cover:
1. ScrapingMetrics — record_scrape, get_domain_day_stats, get_domain_stats,
   get_health_summary, get_failure_groups, get_tracked_domains
2. Monitoring API endpoints — /health, /domains, /failures, /dashboard
3. API key authentication
4. Alert webhook integration
5. No-op mode (no Redis)
"""

from __future__ import annotations

import sys
import time
from datetime import date, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

# ── Pre-load mocks for heavy infrastructure deps ─────────────────────────
# Same pattern as test_scraping_service.py — prevents pulling in
# pydantic-settings / asyncpg / Celery / FastAPI which may not be installed
# in the local dev environment.
_fake_pydantic_settings = MagicMock()
_fake_config_module = MagicMock()
_fake_config_module.settings = MagicMock(
    redis_url="redis://localhost:6379/0",
    celery_broker_url="redis://localhost:6379/1",
    monitoring_api_key="",
    monitoring_alert_threshold=50.0,
    monitoring_alert_webhook_url="",
)

sys.modules.setdefault("pydantic_settings", _fake_pydantic_settings)
sys.modules.setdefault("price_radar.infrastructure.config", _fake_config_module)

# Mock Celery so celery_app can be imported without a real broker
sys.modules.setdefault("celery", MagicMock())
sys.modules.setdefault("celery.schedules", MagicMock())

from price_radar.application.scraping_metrics import (
    DomainDayStats,
    DomainSummary,
    FailureGroup,
    HealthSummary,
    ScrapingMetrics,
    _stats_key,
)

# Try importing FastAPI test dependencies — skip API tests if not available
try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from price_radar.api.monitoring import router as monitoring_router, _format_timestamp

    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

_skip_no_fastapi = pytest.mark.skipif(
    not _HAS_FASTAPI, reason="FastAPI not installed"
)


# ── Fake Redis implementation ────────────────────────────────────────────


class FakeRedis:
    """In-memory Redis-like store for testing metrics.

    Supports hashes, sets, pipelines, and key expiry (TTL stored but not
    enforced — tests run fast enough that expiry doesn't matter).
    """

    def __init__(self) -> None:
        self._hashes: dict[str, dict[str, str]] = {}
        self._sets: dict[str, set[str]] = {}
        self._ttls: dict[str, int] = {}

    # Hash commands
    def hset(self, name: str, key: str | None = None, value: str | None = None,
             mapping: dict[str, str] | None = None) -> int:
        h = self._hashes.setdefault(name, {})
        if mapping:
            h.update(mapping)
            return len(mapping)
        if key is not None and value is not None:
            h[key] = str(value)
            return 1
        return 0

    def hget(self, name: str, key: str) -> str | None:
        return self._hashes.get(name, {}).get(key)

    def hgetall(self, name: str) -> dict[str, str]:
        return dict(self._hashes.get(name, {}))

    def hincrby(self, name: str, key: str, amount: int = 1) -> int:
        h = self._hashes.setdefault(name, {})
        current = int(h.get(key, "0"))
        h[key] = str(current + amount)
        return current + amount

    def hincrbyfloat(self, name: str, key: str, amount: float) -> float:
        h = self._hashes.setdefault(name, {})
        current = float(h.get(key, "0.0"))
        new_val = current + amount
        h[key] = str(new_val)
        return new_val

    def hdel(self, name: str, *keys: str) -> int:
        h = self._hashes.get(name, {})
        removed = 0
        for k in keys:
            if k in h:
                del h[k]
                removed += 1
        return removed

    # Set commands
    def sadd(self, name: str, *values: str) -> int:
        s = self._sets.setdefault(name, set())
        before = len(s)
        s.update(values)
        return len(s) - before

    def smembers(self, name: str) -> set[str]:
        return set(self._sets.get(name, set()))

    # Key commands
    def expire(self, name: str, seconds: int) -> bool:
        self._ttls[name] = seconds
        return True

    def delete(self, *names: str) -> int:
        removed = 0
        for name in names:
            if name in self._hashes:
                del self._hashes[name]
                removed += 1
            if name in self._sets:
                del self._sets[name]
                removed += 1
        return removed

    def llen(self, name: str) -> int:
        return 0  # No list support needed for tests

    # Scan for circuit breaker
    def scan(self, cursor: int = 0, match: str = "*", count: int = 100):
        # Simple implementation: return all matching keys in one go
        import fnmatch
        all_keys = list(self._hashes.keys())
        matched = [k for k in all_keys if fnmatch.fnmatch(k, match)]
        return (0, matched)

    # Pipeline support
    def pipeline(self) -> FakeRedisPipeline:
        return FakeRedisPipeline(self)


class FakeRedisPipeline:
    """Fake Redis pipeline that immediately delegates to the parent FakeRedis."""

    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._results: list = []

    def hset(self, name: str, key: str | None = None, value: str | None = None,
             mapping: dict[str, str] | None = None) -> "FakeRedisPipeline":
        self._results.append(self._redis.hset(name, key, value, mapping=mapping))
        return self

    def hget(self, name: str, key: str) -> "FakeRedisPipeline":
        self._results.append(self._redis.hget(name, key))
        return self

    def hincrby(self, name: str, key: str, amount: int = 1) -> "FakeRedisPipeline":
        self._results.append(self._redis.hincrby(name, key, amount))
        return self

    def hincrbyfloat(self, name: str, key: str, amount: float) -> "FakeRedisPipeline":
        self._results.append(self._redis.hincrbyfloat(name, key, amount))
        return self

    def expire(self, name: str, seconds: int) -> "FakeRedisPipeline":
        self._results.append(self._redis.expire(name, seconds))
        return self

    def sadd(self, name: str, *values: str) -> "FakeRedisPipeline":
        self._results.append(self._redis.sadd(name, *values))
        return self

    def execute(self) -> list:
        results = self._results[:]
        self._results.clear()
        return results


# ══════════════════════════════════════════════════════════════════════════
# ScrapingMetrics — unit tests
# ══════════════════════════════════════════════════════════════════════════


class TestNoOpMode:
    """All operations should be safe no-ops when Redis is None."""

    def test_record_scrape_no_error(self) -> None:
        m = ScrapingMetrics(None)
        m.record_scrape("amazon.com", success=True, fetch_method="httpx", fetch_time=1.0)

    def test_get_tracked_domains_returns_empty(self) -> None:
        m = ScrapingMetrics(None)
        assert m.get_tracked_domains() == []

    def test_get_domain_day_stats_returns_zeros(self) -> None:
        m = ScrapingMetrics(None)
        stats = m.get_domain_day_stats("amazon.com", date.today())
        assert stats.success == 0
        assert stats.failure == 0

    def test_get_domain_stats_returns_zeros(self) -> None:
        m = ScrapingMetrics(None)
        summary = m.get_domain_stats("amazon.com", days=1)
        assert summary.total == 0
        assert summary.success_rate == 0.0

    def test_get_health_summary_returns_defaults(self) -> None:
        m = ScrapingMetrics(None)
        health = m.get_health_summary()
        assert health.total_scrapes_24h == 0
        assert health.active_domains == 0

    def test_get_failure_groups_returns_empty(self) -> None:
        m = ScrapingMetrics(None)
        assert m.get_failure_groups() == []


class TestRecordScrape:
    """Test the record_scrape method with fake Redis."""

    def test_success_increments_counters(self) -> None:
        redis = FakeRedis()
        m = ScrapingMetrics(redis)

        m.record_scrape("amazon.com", success=True, fetch_method="httpx", fetch_time=1.5)

        stats = m.get_domain_day_stats("amazon.com", date.today())
        assert stats.success == 1
        assert stats.failure == 0
        assert stats.method_httpx == 1
        assert stats.total_fetch_time == pytest.approx(1.5, abs=0.01)

    def test_failure_increments_counters(self) -> None:
        redis = FakeRedis()
        m = ScrapingMetrics(redis)

        m.record_scrape("bestbuy.com", success=False, fetch_method="none",
                        fetch_time=0.5, error="timeout")

        stats = m.get_domain_day_stats("bestbuy.com", date.today())
        assert stats.failure == 1
        assert stats.success == 0
        assert stats.method_none == 1
        assert stats.errors == {"timeout": 1}

    def test_multiple_scrapes_accumulate(self) -> None:
        redis = FakeRedis()
        m = ScrapingMetrics(redis)

        for _ in range(3):
            m.record_scrape("amazon.com", success=True, fetch_method="httpx", fetch_time=1.0)
        m.record_scrape("amazon.com", success=False, fetch_method="playwright",
                        fetch_time=3.0, error="extraction_failed")

        stats = m.get_domain_day_stats("amazon.com", date.today())
        assert stats.success == 3
        assert stats.failure == 1
        assert stats.total == 4
        assert stats.method_httpx == 3
        assert stats.method_playwright == 1
        assert stats.success_rate == 75.0
        assert stats.avg_fetch_time == pytest.approx(1.5, abs=0.01)

    def test_tracks_domain_in_global_set(self) -> None:
        redis = FakeRedis()
        m = ScrapingMetrics(redis)

        m.record_scrape("amazon.com", success=True)
        m.record_scrape("etsy.com", success=True)

        domains = m.get_tracked_domains()
        assert "amazon.com" in domains
        assert "etsy.com" in domains

    def test_error_type_colon_normalization(self) -> None:
        """Error strings like 'unexpected_error: ConnectionError: ...' should
        only use the first part as the error key."""
        redis = FakeRedis()
        m = ScrapingMetrics(redis)

        m.record_scrape("example.com", success=False,
                        error="unexpected_error: ConnectionError: refused")

        stats = m.get_domain_day_stats("example.com", date.today())
        assert "unexpected_error" in stats.errors
        assert stats.errors["unexpected_error"] == 1

    def test_playwright_method(self) -> None:
        redis = FakeRedis()
        m = ScrapingMetrics(redis)

        m.record_scrape("bestbuy.com", success=True, fetch_method="playwright",
                        fetch_time=4.5)

        stats = m.get_domain_day_stats("bestbuy.com", date.today())
        assert stats.method_playwright == 1
        assert stats.method_httpx == 0


class TestDomainDayStats:
    """Test DomainDayStats computed properties."""

    def test_success_rate_zero_total(self) -> None:
        stats = DomainDayStats(domain="x.com", day=date.today())
        assert stats.success_rate == 0.0

    def test_avg_fetch_time_zero_total(self) -> None:
        stats = DomainDayStats(domain="x.com", day=date.today())
        assert stats.avg_fetch_time == 0.0

    def test_total_property(self) -> None:
        stats = DomainDayStats(domain="x.com", day=date.today(), success=5, failure=3)
        assert stats.total == 8


class TestDomainSummary:
    """Test DomainSummary computed properties."""

    def test_success_rate(self) -> None:
        s = DomainSummary(domain="x.com", days=1, success=9, failure=1)
        assert s.success_rate == 90.0

    def test_total(self) -> None:
        s = DomainSummary(domain="x.com", days=1, success=5, failure=5)
        assert s.total == 10


class TestGetDomainStats:
    """Test multi-day aggregation via get_domain_stats."""

    def test_single_day(self) -> None:
        redis = FakeRedis()
        m = ScrapingMetrics(redis)

        m.record_scrape("amazon.com", success=True, fetch_method="httpx", fetch_time=1.0)
        m.record_scrape("amazon.com", success=False, error="timeout")

        summary = m.get_domain_stats("amazon.com", days=1)
        assert summary.success == 1
        assert summary.failure == 1
        assert summary.total == 2

    def test_multi_day_aggregation(self) -> None:
        """Manually insert stats for yesterday and verify aggregation."""
        redis = FakeRedis()
        m = ScrapingMetrics(redis)

        # Today
        m.record_scrape("amazon.com", success=True, fetch_time=1.0)

        # Manually set yesterday's data
        yesterday = date.today() - timedelta(days=1)
        key = _stats_key("amazon.com", yesterday)
        redis.hset(key, mapping={
            "success": "5",
            "failure": "2",
            "method:httpx": "4",
            "method:playwright": "1",
            "method:none": "2",
            "total_fetch_time": "10.0",
            "error:timeout": "2",
        })

        summary = m.get_domain_stats("amazon.com", days=2)
        assert summary.success == 6
        assert summary.failure == 2
        assert summary.total == 8
        assert summary.errors.get("timeout") == 2


class TestGetHealthSummary:
    """Test the overall health summary."""

    def test_healthy_state(self) -> None:
        redis = FakeRedis()
        m = ScrapingMetrics(redis)

        for _ in range(10):
            m.record_scrape("amazon.com", success=True)

        health = m.get_health_summary()
        assert health.success_rate_24h == 100.0
        assert health.total_scrapes_24h == 10
        assert health.domains_below_threshold == []

    def test_degraded_state(self) -> None:
        redis = FakeRedis()
        m = ScrapingMetrics(redis)

        # amazon.com: 8/10 success (80%) — above 50% threshold
        for _ in range(8):
            m.record_scrape("amazon.com", success=True)
        for _ in range(2):
            m.record_scrape("amazon.com", success=False, error="timeout")

        # bestbuy.com: 1/10 success (10%) — below threshold
        m.record_scrape("bestbuy.com", success=True)
        for _ in range(9):
            m.record_scrape("bestbuy.com", success=False, error="captcha")

        health = m.get_health_summary(alert_threshold=50.0)
        assert health.total_scrapes_24h == 20
        assert health.success_24h == 9
        assert health.failure_24h == 11
        assert "bestbuy.com" in health.domains_below_threshold
        assert "amazon.com" not in health.domains_below_threshold

    def test_queue_depth_passthrough(self) -> None:
        redis = FakeRedis()
        m = ScrapingMetrics(redis)
        health = m.get_health_summary(queue_depth=42)
        assert health.queue_depth == 42


class TestGetFailureGroups:
    """Test failure grouping by error type and domain."""

    def test_groups_by_error_and_domain(self) -> None:
        redis = FakeRedis()
        m = ScrapingMetrics(redis)

        for _ in range(3):
            m.record_scrape("amazon.com", success=False, error="timeout")
        for _ in range(5):
            m.record_scrape("bestbuy.com", success=False, error="captcha")
        m.record_scrape("amazon.com", success=False, error="extraction_failed")

        groups = m.get_failure_groups(days=1)
        assert len(groups) == 3

        # Should be sorted by count descending
        assert groups[0].error_type == "captcha"
        assert groups[0].domain == "bestbuy.com"
        assert groups[0].count == 5

        assert groups[1].error_type == "timeout"
        assert groups[1].domain == "amazon.com"
        assert groups[1].count == 3

    def test_empty_when_no_failures(self) -> None:
        redis = FakeRedis()
        m = ScrapingMetrics(redis)
        m.record_scrape("amazon.com", success=True)
        groups = m.get_failure_groups()
        assert groups == []


# ══════════════════════════════════════════════════════════════════════════
# Monitoring API — endpoint tests
# ══════════════════════════════════════════════════════════════════════════


@_skip_no_fastapi
class TestMonitoringApiAuth:
    """Test API key authentication on monitoring endpoints."""

    @patch("price_radar.api.monitoring._get_redis", return_value=None)
    @patch("price_radar.api.monitoring.settings")
    def test_no_auth_when_key_empty(self, mock_settings: MagicMock,
                                     mock_redis: MagicMock) -> None:
        """When monitoring_api_key is empty, endpoints should be accessible."""
        mock_settings.monitoring_api_key = ""
        mock_settings.monitoring_alert_threshold = 50.0
        mock_settings.redis_url = ""
        mock_settings.celery_broker_url = ""

        app = FastAPI()
        app.include_router(monitoring_router)
        client = TestClient(app)

        resp = client.get("/internal/scraping/health")
        assert resp.status_code == 200

    @patch("price_radar.api.monitoring._get_redis", return_value=None)
    @patch("price_radar.api.monitoring.settings")
    def test_rejects_missing_key(self, mock_settings: MagicMock,
                                  mock_redis: MagicMock) -> None:
        """When monitoring_api_key is set, requests without key get 403."""
        mock_settings.monitoring_api_key = "secret-key-123"
        mock_settings.monitoring_alert_threshold = 50.0
        mock_settings.redis_url = ""
        mock_settings.celery_broker_url = ""

        app = FastAPI()
        app.include_router(monitoring_router)
        client = TestClient(app)

        resp = client.get("/internal/scraping/health")
        assert resp.status_code == 403

    @patch("price_radar.api.monitoring._get_redis", return_value=None)
    @patch("price_radar.api.monitoring.settings")
    def test_accepts_valid_key(self, mock_settings: MagicMock,
                                mock_redis: MagicMock) -> None:
        """When monitoring_api_key is set, requests with correct key succeed."""
        mock_settings.monitoring_api_key = "secret-key-123"
        mock_settings.monitoring_alert_threshold = 50.0
        mock_settings.redis_url = ""
        mock_settings.celery_broker_url = ""

        app = FastAPI()
        app.include_router(monitoring_router)
        client = TestClient(app)

        resp = client.get("/internal/scraping/health",
                          headers={"X-API-Key": "secret-key-123"})
        assert resp.status_code == 200

    @patch("price_radar.api.monitoring._get_redis", return_value=None)
    @patch("price_radar.api.monitoring.settings")
    def test_rejects_wrong_key(self, mock_settings: MagicMock,
                                mock_redis: MagicMock) -> None:
        """When monitoring_api_key is set, wrong key returns 403."""
        mock_settings.monitoring_api_key = "secret-key-123"
        mock_settings.monitoring_alert_threshold = 50.0
        mock_settings.redis_url = ""
        mock_settings.celery_broker_url = ""

        app = FastAPI()
        app.include_router(monitoring_router)
        client = TestClient(app)

        resp = client.get("/internal/scraping/health",
                          headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 403


@_skip_no_fastapi
class TestHealthEndpoint:
    """Test GET /internal/scraping/health."""

    @patch("price_radar.api.monitoring._get_queue_depth", return_value=5)
    @patch("price_radar.api.monitoring._get_redis")
    @patch("price_radar.api.monitoring.settings")
    def test_returns_health_data(self, mock_settings: MagicMock,
                                  mock_get_redis: MagicMock,
                                  mock_queue: MagicMock) -> None:
        mock_settings.monitoring_api_key = ""
        mock_settings.monitoring_alert_threshold = 50.0
        mock_settings.redis_url = ""
        mock_settings.celery_broker_url = ""

        redis = FakeRedis()
        mock_get_redis.return_value = redis

        # Record some data
        m = ScrapingMetrics(redis)
        for _ in range(8):
            m.record_scrape("amazon.com", success=True)
        for _ in range(2):
            m.record_scrape("amazon.com", success=False, error="timeout")

        app = FastAPI()
        app.include_router(monitoring_router)
        client = TestClient(app)

        resp = client.get("/internal/scraping/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_scrapes_24h"] == 10
        assert data["success_24h"] == 8
        assert data["failure_24h"] == 2
        assert data["success_rate_24h"] == 80.0
        assert data["queue_depth"] == 5
        assert data["status"] == "healthy"


@_skip_no_fastapi
class TestDomainsEndpoint:
    """Test GET /internal/scraping/domains."""

    @patch("price_radar.api.monitoring._get_redis")
    @patch("price_radar.api.monitoring.settings")
    def test_returns_per_domain_stats(self, mock_settings: MagicMock,
                                      mock_get_redis: MagicMock) -> None:
        mock_settings.monitoring_api_key = ""
        mock_settings.monitoring_alert_threshold = 50.0
        mock_settings.redis_url = ""
        mock_settings.celery_broker_url = ""

        redis = FakeRedis()
        mock_get_redis.return_value = redis

        m = ScrapingMetrics(redis)
        m.record_scrape("amazon.com", success=True, fetch_method="httpx",
                        fetch_time=1.2)
        m.record_scrape("bestbuy.com", success=False, fetch_method="playwright",
                        fetch_time=3.5, error="captcha")

        app = FastAPI()
        app.include_router(monitoring_router)
        client = TestClient(app)

        resp = client.get("/internal/scraping/domains")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

        # Should be sorted by total desc
        domains = [d["domain"] for d in data]
        assert "amazon.com" in domains
        assert "bestbuy.com" in domains

        # Check structure
        amazon = next(d for d in data if d["domain"] == "amazon.com")
        assert amazon["success"] == 1
        assert amazon["method_distribution"]["httpx"] == 1
        assert "circuit_breaker" in amazon
        assert amazon["circuit_breaker"]["state"] == "closed"


@_skip_no_fastapi
class TestFailuresEndpoint:
    """Test GET /internal/scraping/failures."""

    @patch("price_radar.api.monitoring._get_redis")
    @patch("price_radar.api.monitoring.settings")
    def test_returns_failure_groups(self, mock_settings: MagicMock,
                                    mock_get_redis: MagicMock) -> None:
        mock_settings.monitoring_api_key = ""
        mock_settings.monitoring_alert_threshold = 50.0
        mock_settings.redis_url = ""
        mock_settings.celery_broker_url = ""

        redis = FakeRedis()
        mock_get_redis.return_value = redis

        m = ScrapingMetrics(redis)
        for _ in range(5):
            m.record_scrape("amazon.com", success=False, error="timeout")

        app = FastAPI()
        app.include_router(monitoring_router)
        client = TestClient(app)

        resp = client.get("/internal/scraping/failures")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["error_type"] == "timeout"
        assert data[0]["domain"] == "amazon.com"
        assert data[0]["count"] == 5


@_skip_no_fastapi
class TestDashboardEndpoint:
    """Test GET /internal/scraping/dashboard."""

    @patch("price_radar.api.monitoring._get_queue_depth", return_value=0)
    @patch("price_radar.api.monitoring._get_redis")
    @patch("price_radar.api.monitoring.settings")
    def test_returns_html(self, mock_settings: MagicMock,
                           mock_get_redis: MagicMock,
                           mock_queue: MagicMock) -> None:
        mock_settings.monitoring_api_key = ""
        mock_settings.monitoring_alert_threshold = 50.0
        mock_settings.redis_url = ""
        mock_settings.celery_broker_url = ""

        redis = FakeRedis()
        mock_get_redis.return_value = redis

        m = ScrapingMetrics(redis)
        m.record_scrape("amazon.com", success=True, fetch_method="httpx", fetch_time=1.0)

        app = FastAPI()
        app.include_router(monitoring_router)
        client = TestClient(app)

        resp = client.get("/internal/scraping/dashboard")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Price Radar" in resp.text
        assert "amazon.com" in resp.text

    @patch("price_radar.api.monitoring._get_queue_depth", return_value=0)
    @patch("price_radar.api.monitoring._get_redis")
    @patch("price_radar.api.monitoring.settings")
    def test_dashboard_empty_state(self, mock_settings: MagicMock,
                                    mock_get_redis: MagicMock,
                                    mock_queue: MagicMock) -> None:
        """Dashboard should render without errors even with no data."""
        mock_settings.monitoring_api_key = ""
        mock_settings.monitoring_alert_threshold = 50.0
        mock_settings.redis_url = ""
        mock_settings.celery_broker_url = ""

        mock_get_redis.return_value = FakeRedis()

        app = FastAPI()
        app.include_router(monitoring_router)
        client = TestClient(app)

        resp = client.get("/internal/scraping/dashboard")
        assert resp.status_code == 200
        assert "No scraping data yet" in resp.text

    @patch("price_radar.api.monitoring._get_queue_depth", return_value=0)
    @patch("price_radar.api.monitoring._get_redis")
    @patch("price_radar.api.monitoring.settings")
    def test_dashboard_shows_alerts(self, mock_settings: MagicMock,
                                     mock_get_redis: MagicMock,
                                     mock_queue: MagicMock) -> None:
        """Dashboard should show alert box when domains are below threshold."""
        mock_settings.monitoring_api_key = ""
        mock_settings.monitoring_alert_threshold = 50.0
        mock_settings.redis_url = ""
        mock_settings.celery_broker_url = ""

        redis = FakeRedis()
        mock_get_redis.return_value = redis

        m = ScrapingMetrics(redis)
        # All failures for bestbuy.com — will be below threshold
        for _ in range(10):
            m.record_scrape("bestbuy.com", success=False, error="captcha")

        app = FastAPI()
        app.include_router(monitoring_router)
        client = TestClient(app)

        resp = client.get("/internal/scraping/dashboard")
        assert resp.status_code == 200
        assert "bestbuy.com" in resp.text
        assert "alert-box" in resp.text


# ══════════════════════════════════════════════════════════════════════════
# Alert webhook tests
# ══════════════════════════════════════════════════════════════════════════


class TestMonitoringAlerts:
    """Test the webhook alert functionality."""

    @patch("price_radar.application.monitoring_alerts.httpx.post")
    def test_sends_webhook_on_degraded_domains(self, mock_post: MagicMock) -> None:
        from price_radar.application.monitoring_alerts import send_alert

        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_post.return_value = mock_resp

        result = send_alert(
            webhook_url="https://hooks.slack.com/test",
            domains=["amazon.com", "bestbuy.com"],
            threshold=50.0,
        )

        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert "amazon.com" in payload["text"]
        assert payload["threshold"] == 50.0

    @patch("price_radar.application.monitoring_alerts.httpx.post")
    def test_returns_false_on_http_error(self, mock_post: MagicMock) -> None:
        from price_radar.application.monitoring_alerts import send_alert

        mock_resp = MagicMock()
        mock_resp.is_success = False
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_post.return_value = mock_resp

        result = send_alert(
            webhook_url="https://hooks.slack.com/test",
            domains=["amazon.com"],
            threshold=50.0,
        )
        assert result is False

    @patch("price_radar.application.monitoring_alerts.httpx.post")
    def test_returns_false_on_exception(self, mock_post: MagicMock) -> None:
        from price_radar.application.monitoring_alerts import send_alert

        mock_post.side_effect = Exception("connection refused")

        result = send_alert(
            webhook_url="https://hooks.slack.com/test",
            domains=["amazon.com"],
            threshold=50.0,
        )
        assert result is False

    def test_returns_false_when_no_webhook_url(self) -> None:
        from price_radar.application.monitoring_alerts import send_alert

        result = send_alert(
            webhook_url="",
            domains=["amazon.com"],
            threshold=50.0,
        )
        assert result is False

    def test_returns_false_when_no_domains(self) -> None:
        from price_radar.application.monitoring_alerts import send_alert

        result = send_alert(
            webhook_url="https://hooks.slack.com/test",
            domains=[],
            threshold=50.0,
        )
        assert result is False


# ══════════════════════════════════════════════════════════════════════════
# Helper function tests
# ══════════════════════════════════════════════════════════════════════════


class TestStatsKey:
    """Test the _stats_key helper."""

    def test_format(self) -> None:
        key = _stats_key("amazon.com", date(2025, 1, 15))
        assert key == "scrape:stats:amazon.com:2025-01-15"

    def test_different_domains(self) -> None:
        k1 = _stats_key("amazon.com", date.today())
        k2 = _stats_key("bestbuy.com", date.today())
        assert k1 != k2


@_skip_no_fastapi
class TestFormatTimestamp:
    """Test the timestamp formatter."""

    def test_none_returns_none(self) -> None:
        assert _format_timestamp(None) is None

    def test_valid_timestamp(self) -> None:
        result = _format_timestamp(1700000000.0)
        assert result is not None
        assert "2023" in result  # Nov 2023
