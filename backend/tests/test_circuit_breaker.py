"""Tests for DomainCircuitBreaker — per-domain circuit breaker with Redis.

Tests cover:
1. State transitions: CLOSED→OPEN, OPEN→HALF_OPEN, HALF_OPEN→CLOSED, HALF_OPEN→OPEN
2. Failure threshold and exponential backoff
3. No-op mode (no Redis)
4. get_status() and get_open_domains()
5. PageFetcher integration — circuit breaker checked before fetch
6. reset()
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from price_radar.application.circuit_breaker import (
    DEFAULT_FAILURE_THRESHOLD,
    DEFAULT_MAX_RECOVERY_TIMEOUT,
    DEFAULT_RECOVERY_TIMEOUT,
    CircuitState,
    CircuitStatus,
    DomainCircuitBreaker,
)


# ═══════════════════════════════════════════════════════════════════════
# Helper: mock Redis hash
# ═══════════════════════════════════════════════════════════════════════


class FakeRedisHash:
    """In-memory Redis-like hash store for testing circuit breaker.

    Supports hset, hget, hdel, hincrby, delete, expire, scan — the
    exact subset used by DomainCircuitBreaker.
    """

    def __init__(self) -> None:
        self._data: dict[str, dict[str, str]] = {}

    def hset(self, key: str, field: str | None = None, value: str | None = None,
             mapping: dict[str, str] | None = None) -> int:
        if key not in self._data:
            self._data[key] = {}
        if mapping:
            self._data[key].update(mapping)
            return len(mapping)
        if field is not None and value is not None:
            self._data[key][field] = str(value)
            return 1
        return 0

    def hget(self, key: str, field: str) -> str | None:
        return self._data.get(key, {}).get(field)

    def hdel(self, key: str, *fields: str) -> int:
        removed = 0
        if key in self._data:
            for f in fields:
                if f in self._data[key]:
                    del self._data[key][f]
                    removed += 1
        return removed

    def hincrby(self, key: str, field: str, amount: int = 1) -> int:
        if key not in self._data:
            self._data[key] = {}
        current = int(self._data[key].get(field, "0"))
        new_val = current + amount
        self._data[key][field] = str(new_val)
        return new_val

    def delete(self, key: str) -> int:
        if key in self._data:
            del self._data[key]
            return 1
        return 0

    def expire(self, key: str, seconds: int) -> bool:
        return True  # No-op for tests

    def scan(self, cursor: int = 0, match: str = "*", count: int = 100) -> tuple[int, list[str]]:
        prefix = match.rstrip("*")
        matched = [k for k in self._data if k.startswith(prefix)]
        return (0, matched)

    def pipeline(self, transaction: bool = True) -> "FakeRedisHash":
        return self  # Simplified — no real pipelining needed for CB tests

    def execute(self) -> list:
        return []  # Not used by circuit breaker


# ═══════════════════════════════════════════════════════════════════════
# CircuitState enum tests
# ═══════════════════════════════════════════════════════════════════════


class TestCircuitState:
    """Test CircuitState enum values."""

    def test_values(self) -> None:
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"

    def test_from_string(self) -> None:
        assert CircuitState("closed") == CircuitState.CLOSED
        assert CircuitState("open") == CircuitState.OPEN
        assert CircuitState("half_open") == CircuitState.HALF_OPEN


# ═══════════════════════════════════════════════════════════════════════
# No-op mode (no Redis)
# ═══════════════════════════════════════════════════════════════════════


class TestNoOpMode:
    """When redis_client is None, all operations should be no-ops."""

    def test_allow_request_returns_true(self) -> None:
        cb = DomainCircuitBreaker()
        assert cb.allow_request("bestbuy.com") is True

    def test_record_success_does_not_error(self) -> None:
        cb = DomainCircuitBreaker()
        cb.record_success("bestbuy.com")  # Should not raise

    def test_record_failure_does_not_error(self) -> None:
        cb = DomainCircuitBreaker()
        cb.record_failure("bestbuy.com")  # Should not raise

    def test_get_status_returns_closed(self) -> None:
        cb = DomainCircuitBreaker()
        status = cb.get_status("bestbuy.com")
        assert status.state == CircuitState.CLOSED
        assert status.failure_count == 0

    def test_get_open_domains_returns_empty(self) -> None:
        cb = DomainCircuitBreaker()
        assert cb.get_open_domains() == []

    def test_reset_does_not_error(self) -> None:
        cb = DomainCircuitBreaker()
        cb.reset("bestbuy.com")


# ═══════════════════════════════════════════════════════════════════════
# CLOSED state tests
# ═══════════════════════════════════════════════════════════════════════


class TestClosedState:
    """Test behaviour in CLOSED state."""

    def test_allow_request_when_no_state(self) -> None:
        """Fresh domain (no Redis entry) should allow requests."""
        redis = FakeRedisHash()
        cb = DomainCircuitBreaker(redis)
        assert cb.allow_request("amazon.com") is True

    def test_failures_below_threshold_stay_closed(self) -> None:
        """4 failures (below threshold=5) should keep circuit CLOSED."""
        redis = FakeRedisHash()
        cb = DomainCircuitBreaker(redis, failure_threshold=5)

        for _ in range(4):
            cb.record_failure("amazon.com")

        status = cb.get_status("amazon.com")
        assert status.state == CircuitState.CLOSED
        assert status.failure_count == 4
        assert cb.allow_request("amazon.com") is True

    def test_success_resets_failure_count(self) -> None:
        """Success should reset failure_count to 0."""
        redis = FakeRedisHash()
        cb = DomainCircuitBreaker(redis, failure_threshold=5)

        for _ in range(3):
            cb.record_failure("amazon.com")
        cb.record_success("amazon.com")

        status = cb.get_status("amazon.com")
        assert status.failure_count == 0
        assert status.state == CircuitState.CLOSED


# ═══════════════════════════════════════════════════════════════════════
# CLOSED → OPEN transition
# ═══════════════════════════════════════════════════════════════════════


class TestClosedToOpen:
    """Test transition from CLOSED to OPEN at failure threshold."""

    def test_opens_at_threshold(self) -> None:
        """5 consecutive failures should open the circuit."""
        redis = FakeRedisHash()
        cb = DomainCircuitBreaker(redis, failure_threshold=5)

        for _ in range(5):
            cb.record_failure("bestbuy.com")

        status = cb.get_status("bestbuy.com")
        assert status.state == CircuitState.OPEN
        assert status.failure_count == 5
        assert status.opened_at is not None
        assert status.next_retry_at is not None

    def test_open_rejects_requests(self) -> None:
        """OPEN circuit should reject requests."""
        redis = FakeRedisHash()
        cb = DomainCircuitBreaker(redis, failure_threshold=3)

        for _ in range(3):
            cb.record_failure("etsy.com")

        assert cb.allow_request("etsy.com") is False

    def test_next_retry_at_set_correctly(self) -> None:
        """next_retry_at should be now + recovery_timeout."""
        redis = FakeRedisHash()
        cb = DomainCircuitBreaker(
            redis, failure_threshold=3, recovery_timeout=1800.0,
        )

        before = time.time()
        for _ in range(3):
            cb.record_failure("target.com")
        after = time.time()

        status = cb.get_status("target.com")
        assert status.next_retry_at is not None
        assert before + 1800.0 <= status.next_retry_at <= after + 1800.0 + 1.0


# ═══════════════════════════════════════════════════════════════════════
# OPEN → HALF_OPEN transition
# ═══════════════════════════════════════════════════════════════════════


class TestOpenToHalfOpen:
    """Test transition from OPEN to HALF_OPEN when timeout expires."""

    def test_transitions_after_timeout(self) -> None:
        """After next_retry_at, allow_request should return True (HALF_OPEN)."""
        redis = FakeRedisHash()
        cb = DomainCircuitBreaker(redis, failure_threshold=3, recovery_timeout=1.0)

        for _ in range(3):
            cb.record_failure("bestbuy.com")

        # Simulate timeout expiry by backdating next_retry_at
        key = "circuit:bestbuy.com"
        redis.hset(key, "next_retry_at", str(time.time() - 10))

        assert cb.allow_request("bestbuy.com") is True
        status = cb.get_status("bestbuy.com")
        assert status.state == CircuitState.HALF_OPEN

    def test_does_not_transition_before_timeout(self) -> None:
        """Before next_retry_at, request should still be rejected."""
        redis = FakeRedisHash()
        cb = DomainCircuitBreaker(redis, failure_threshold=3, recovery_timeout=3600.0)

        for _ in range(3):
            cb.record_failure("bestbuy.com")

        assert cb.allow_request("bestbuy.com") is False


# ═══════════════════════════════════════════════════════════════════════
# HALF_OPEN → CLOSED transition
# ═══════════════════════════════════════════════════════════════════════


class TestHalfOpenToClosed:
    """Test transition from HALF_OPEN to CLOSED on success."""

    def test_success_closes_circuit(self) -> None:
        """Success in HALF_OPEN should close the circuit."""
        redis = FakeRedisHash()
        cb = DomainCircuitBreaker(redis, failure_threshold=3, recovery_timeout=1.0)

        # Open the circuit
        for _ in range(3):
            cb.record_failure("bestbuy.com")

        # Trigger HALF_OPEN
        redis.hset("circuit:bestbuy.com", "next_retry_at", str(time.time() - 10))
        cb.allow_request("bestbuy.com")

        # Record success
        cb.record_success("bestbuy.com")

        status = cb.get_status("bestbuy.com")
        assert status.state == CircuitState.CLOSED
        assert status.failure_count == 0
        assert status.backoff_multiplier == 1


# ═══════════════════════════════════════════════════════════════════════
# HALF_OPEN → OPEN transition (with exponential backoff)
# ═══════════════════════════════════════════════════════════════════════


class TestHalfOpenToOpen:
    """Test transition from HALF_OPEN back to OPEN on failure."""

    def test_failure_reopens_circuit(self) -> None:
        """Failure in HALF_OPEN should reopen the circuit."""
        redis = FakeRedisHash()
        cb = DomainCircuitBreaker(redis, failure_threshold=3, recovery_timeout=3600.0)

        # Open the circuit
        for _ in range(3):
            cb.record_failure("etsy.com")

        # Trigger HALF_OPEN
        redis.hset("circuit:etsy.com", "next_retry_at", str(time.time() - 10))
        cb.allow_request("etsy.com")

        # Probe fails
        cb.record_failure("etsy.com")

        status = cb.get_status("etsy.com")
        assert status.state == CircuitState.OPEN
        assert status.backoff_multiplier == 2

    def test_exponential_backoff_increases(self) -> None:
        """Each HALF_OPEN failure should increase the backoff multiplier."""
        redis = FakeRedisHash()
        cb = DomainCircuitBreaker(
            redis, failure_threshold=2, recovery_timeout=100.0,
            backoff_factor=2.0,
        )

        # First open
        for _ in range(2):
            cb.record_failure("target.com")

        # First probe fails
        redis.hset("circuit:target.com", "next_retry_at", str(time.time() - 1))
        cb.allow_request("target.com")
        cb.record_failure("target.com")  # HALF_OPEN → OPEN, multiplier=2

        status = cb.get_status("target.com")
        assert status.backoff_multiplier == 2

        # Second probe fails
        redis.hset("circuit:target.com", "next_retry_at", str(time.time() - 1))
        cb.allow_request("target.com")
        cb.record_failure("target.com")  # HALF_OPEN → OPEN, multiplier=3

        status = cb.get_status("target.com")
        assert status.backoff_multiplier == 3

    def test_backoff_timeout_increases(self) -> None:
        """Recovery timeout should increase with backoff multiplier."""
        redis = FakeRedisHash()
        cb = DomainCircuitBreaker(
            redis, failure_threshold=2, recovery_timeout=3600.0,
            backoff_factor=2.0,
        )

        # Open circuit (multiplier=1, timeout=3600)
        before = time.time()
        for _ in range(2):
            cb.record_failure("target.com")

        status1 = cb.get_status("target.com")
        timeout1 = (status1.next_retry_at or 0) - (status1.opened_at or 0)
        assert 3590 <= timeout1 <= 3610  # ~3600

        # First probe fails (multiplier=2, timeout=7200)
        redis.hset("circuit:target.com", "next_retry_at", str(time.time() - 1))
        cb.allow_request("target.com")
        before2 = time.time()
        cb.record_failure("target.com")

        status2 = cb.get_status("target.com")
        timeout2 = (status2.next_retry_at or 0) - (status2.opened_at or 0)
        assert 7190 <= timeout2 <= 7210  # ~7200

    def test_backoff_capped_at_max(self) -> None:
        """Backoff should be capped at max_recovery_timeout."""
        redis = FakeRedisHash()
        cb = DomainCircuitBreaker(
            redis, failure_threshold=1, recovery_timeout=3600.0,
            backoff_factor=10.0, max_recovery_timeout=86400.0,
        )

        # Open circuit
        cb.record_failure("x.com")

        # Probe fails repeatedly
        for _ in range(10):
            redis.hset("circuit:x.com", "next_retry_at", str(time.time() - 1))
            cb.allow_request("x.com")
            cb.record_failure("x.com")

        status = cb.get_status("x.com")
        timeout = (status.next_retry_at or 0) - (status.opened_at or 0)
        assert timeout <= 86400.0 + 1.0  # Capped at max


# ═══════════════════════════════════════════════════════════════════════
# get_status() tests
# ═══════════════════════════════════════════════════════════════════════


class TestGetStatus:
    """Test get_status() returns correct CircuitStatus."""

    def test_fresh_domain(self) -> None:
        redis = FakeRedisHash()
        cb = DomainCircuitBreaker(redis)
        status = cb.get_status("unknown.com")
        assert status.domain == "unknown.com"
        assert status.state == CircuitState.CLOSED
        assert status.failure_count == 0

    def test_after_failures(self) -> None:
        redis = FakeRedisHash()
        cb = DomainCircuitBreaker(redis, failure_threshold=10)
        for _ in range(3):
            cb.record_failure("test.com")
        status = cb.get_status("test.com")
        assert status.failure_count == 3
        assert status.last_failure_at is not None


# ═══════════════════════════════════════════════════════════════════════
# get_open_domains() tests
# ═══════════════════════════════════════════════════════════════════════


class TestGetOpenDomains:
    """Test get_open_domains() scanning."""

    def test_returns_open_domains(self) -> None:
        redis = FakeRedisHash()
        cb = DomainCircuitBreaker(redis, failure_threshold=2)

        # Open two domains
        for _ in range(2):
            cb.record_failure("a.com")
            cb.record_failure("b.com")

        # Keep one closed
        cb.record_failure("c.com")

        open_domains = cb.get_open_domains()
        assert sorted(open_domains) == ["a.com", "b.com"]

    def test_returns_empty_when_all_closed(self) -> None:
        redis = FakeRedisHash()
        cb = DomainCircuitBreaker(redis, failure_threshold=5)
        cb.record_failure("a.com")
        assert cb.get_open_domains() == []


# ═══════════════════════════════════════════════════════════════════════
# reset() tests
# ═══════════════════════════════════════════════════════════════════════


class TestReset:
    """Test reset() clears circuit data."""

    def test_reset_clears_state(self) -> None:
        redis = FakeRedisHash()
        cb = DomainCircuitBreaker(redis, failure_threshold=2)

        for _ in range(2):
            cb.record_failure("test.com")

        assert cb.get_status("test.com").state == CircuitState.OPEN

        cb.reset("test.com")
        status = cb.get_status("test.com")
        assert status.state == CircuitState.CLOSED
        assert status.failure_count == 0


# ═══════════════════════════════════════════════════════════════════════
# Default configuration tests
# ═══════════════════════════════════════════════════════════════════════


class TestDefaults:
    """Test default configuration values."""

    def test_failure_threshold(self) -> None:
        assert DEFAULT_FAILURE_THRESHOLD == 5

    def test_recovery_timeout(self) -> None:
        assert DEFAULT_RECOVERY_TIMEOUT == 3600.0

    def test_max_recovery_timeout(self) -> None:
        assert DEFAULT_MAX_RECOVERY_TIMEOUT == 86400.0


# ═══════════════════════════════════════════════════════════════════════
# PageFetcher integration — circuit breaker checked before fetch
# ═══════════════════════════════════════════════════════════════════════


class TestPageFetcherCircuitIntegration:
    """Test that PageFetcher respects the circuit breaker."""

    @patch("price_radar.application.price_extraction.fetcher.httpx.get")
    def test_open_circuit_skips_fetch(self, mock_httpx_get: MagicMock) -> None:
        """When circuit is OPEN, fetch should return error without hitting network."""
        from price_radar.application.price_extraction.fetcher import PageFetcher

        mock_cb = MagicMock(spec=DomainCircuitBreaker)
        mock_cb.allow_request.return_value = False

        fetcher = PageFetcher(use_playwright=False, circuit_breaker=mock_cb)
        result = fetcher.fetch("https://www.bestbuy.com/site/product")

        assert result.error == "circuit_open"
        assert result.success is False
        mock_httpx_get.assert_not_called()

    @patch("price_radar.application.price_extraction.fetcher.httpx.get")
    def test_closed_circuit_allows_fetch(self, mock_httpx_get: MagicMock) -> None:
        """When circuit is CLOSED, fetch should proceed normally."""
        from price_radar.application.price_extraction.fetcher import PageFetcher

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html>" + "x" * 600 + "</html>"
        mock_response.raise_for_status = MagicMock()
        mock_httpx_get.return_value = mock_response

        mock_cb = MagicMock(spec=DomainCircuitBreaker)
        mock_cb.allow_request.return_value = True

        fetcher = PageFetcher(use_playwright=False, circuit_breaker=mock_cb)
        result = fetcher.fetch("https://www.amazon.com/dp/B0X")

        assert result.success is True
        mock_cb.record_success.assert_called_once_with("amazon.com")

    @patch("price_radar.application.price_extraction.fetcher.httpx.get")
    def test_fetch_failure_records_failure(self, mock_httpx_get: MagicMock) -> None:
        """Failed fetch should record failure on the circuit breaker."""
        from price_radar.application.price_extraction.fetcher import PageFetcher

        mock_httpx_get.side_effect = httpx.ConnectError("connection refused")

        mock_cb = MagicMock(spec=DomainCircuitBreaker)
        mock_cb.allow_request.return_value = True

        fetcher = PageFetcher(use_playwright=False, circuit_breaker=mock_cb)
        result = fetcher.fetch("https://www.amazon.com/dp/B0X")

        assert result.success is False
        mock_cb.record_failure.assert_called_once_with("amazon.com")

    @patch("price_radar.application.price_extraction.fetcher.httpx.get")
    def test_open_circuit_returns_empty_extraction(self, mock_httpx_get: MagicMock) -> None:
        """fetch_and_extract with OPEN circuit should return empty extraction."""
        from price_radar.application.price_extraction.fetcher import PageFetcher

        mock_cb = MagicMock(spec=DomainCircuitBreaker)
        mock_cb.allow_request.return_value = False

        fetcher = PageFetcher(use_playwright=False, circuit_breaker=mock_cb)
        fetch_result, extraction = fetcher.fetch_and_extract(
            "https://www.bestbuy.com/site/product"
        )

        assert fetch_result.error == "circuit_open"
        assert extraction.success is False
        mock_httpx_get.assert_not_called()

    def test_no_circuit_breaker_works(self) -> None:
        """When no circuit_breaker is set, fetch should work normally."""
        from price_radar.application.price_extraction.fetcher import PageFetcher

        with patch("price_radar.application.price_extraction.fetcher.httpx.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "<html>" + "x" * 600 + "</html>"
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            fetcher = PageFetcher(use_playwright=False)
            result = fetcher.fetch("https://example.com")
            assert result.success


# ═══════════════════════════════════════════════════════════════════════
# Full lifecycle integration test
# ═══════════════════════════════════════════════════════════════════════


class TestFullLifecycle:
    """End-to-end circuit breaker lifecycle with FakeRedisHash."""

    def test_closed_to_open_to_half_open_to_closed(self) -> None:
        """Full cycle: CLOSED → OPEN → HALF_OPEN → CLOSED."""
        redis = FakeRedisHash()
        cb = DomainCircuitBreaker(
            redis, failure_threshold=3, recovery_timeout=1.0,
        )

        # 1. CLOSED — requests allowed
        assert cb.allow_request("test.com") is True
        assert cb.get_status("test.com").state == CircuitState.CLOSED

        # 2. 3 failures → OPEN
        for _ in range(3):
            cb.record_failure("test.com")
        assert cb.get_status("test.com").state == CircuitState.OPEN
        assert cb.allow_request("test.com") is False

        # 3. Simulate timeout → HALF_OPEN
        redis.hset("circuit:test.com", "next_retry_at", str(time.time() - 1))
        assert cb.allow_request("test.com") is True
        assert cb.get_status("test.com").state == CircuitState.HALF_OPEN

        # 4. Probe succeeds → CLOSED
        cb.record_success("test.com")
        assert cb.get_status("test.com").state == CircuitState.CLOSED
        assert cb.get_status("test.com").failure_count == 0

    def test_closed_to_open_to_half_open_to_open(self) -> None:
        """CLOSED → OPEN → HALF_OPEN → OPEN (probe fails)."""
        redis = FakeRedisHash()
        cb = DomainCircuitBreaker(
            redis, failure_threshold=3, recovery_timeout=1.0,
        )

        # Open the circuit
        for _ in range(3):
            cb.record_failure("test.com")

        # Transition to HALF_OPEN
        redis.hset("circuit:test.com", "next_retry_at", str(time.time() - 1))
        cb.allow_request("test.com")

        # Probe fails → back to OPEN
        cb.record_failure("test.com")
        assert cb.get_status("test.com").state == CircuitState.OPEN
        assert cb.get_status("test.com").backoff_multiplier == 2
