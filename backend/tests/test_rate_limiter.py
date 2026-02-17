"""Tests for DomainRateLimiter — per-domain rate limiting with Redis.

Tests cover:
1. RateConfig and domain config lookup
2. extract_domain() URL parsing
3. DomainRateLimiter.acquire() — sliding window logic with mock Redis
4. DomainRateLimiter.wait_for_slot() — blocking wait / RateLimitExceeded
5. DomainRateLimiter no-op mode (no Redis)
6. PageFetcher integration — rate limiter called before fetch
7. Task-level RateLimitExceeded re-queue behaviour
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, call, patch

import pytest

from price_radar.application.rate_limiter import (
    DEFAULT_RATE_LIMITS,
    DEFAULT_UNKNOWN_RATE,
    DomainRateLimiter,
    RateConfig,
    RateLimitExceeded,
    extract_domain,
)


# ═══════════════════════════════════════════════════════════════════════
# extract_domain() tests
# ═══════════════════════════════════════════════════════════════════════


class TestExtractDomain:
    """Test URL → base domain extraction."""

    def test_simple_url(self) -> None:
        assert extract_domain("https://www.amazon.com/dp/B0X") == "amazon.com"

    def test_no_www(self) -> None:
        assert extract_domain("https://amazon.com/dp/B0X") == "amazon.com"

    def test_subdomain(self) -> None:
        assert extract_domain("https://uk.gymshark.com/products/foo") == "gymshark.com"

    def test_port_stripped(self) -> None:
        assert extract_domain("http://localhost:8080/path") == "localhost"

    def test_complex_subdomain(self) -> None:
        assert extract_domain("https://shop.us.nike.com/product") == "nike.com"

    def test_https_not_required(self) -> None:
        assert extract_domain("http://www.etsy.com/listing/123") == "etsy.com"


# ═══════════════════════════════════════════════════════════════════════
# RateConfig tests
# ═══════════════════════════════════════════════════════════════════════


class TestRateConfig:
    """Test RateConfig dataclass."""

    def test_defaults(self) -> None:
        config = RateConfig(requests_per_minute=10)
        assert config.requests_per_minute == 10
        assert config.window_seconds == 60

    def test_custom_window(self) -> None:
        config = RateConfig(requests_per_minute=5, window_seconds=120)
        assert config.window_seconds == 120

    def test_frozen(self) -> None:
        config = RateConfig(requests_per_minute=10)
        with pytest.raises(AttributeError):
            config.requests_per_minute = 20  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════
# DomainRateLimiter.get_config() tests
# ═══════════════════════════════════════════════════════════════════════


class TestGetConfig:
    """Test domain → RateConfig lookup."""

    def test_known_domain(self) -> None:
        limiter = DomainRateLimiter()
        config = limiter.get_config("amazon.com")
        assert config.requests_per_minute == 10

    def test_aggressive_domain(self) -> None:
        limiter = DomainRateLimiter()
        config = limiter.get_config("etsy.com")
        assert config.requests_per_minute == 2

    def test_unknown_domain(self) -> None:
        limiter = DomainRateLimiter()
        config = limiter.get_config("some-random-shop.com")
        assert config == DEFAULT_UNKNOWN_RATE

    def test_base_domain_fallback(self) -> None:
        """Subdomain should match the base domain config."""
        limiter = DomainRateLimiter()
        config = limiter.get_config("uk.amazon.com")
        assert config.requests_per_minute == 10

    def test_custom_rate_limits(self) -> None:
        custom = {"custom-shop.com": RateConfig(requests_per_minute=1)}
        limiter = DomainRateLimiter(rate_limits=custom)
        assert limiter.get_config("custom-shop.com").requests_per_minute == 1
        # Default still available
        assert limiter.get_config("amazon.com").requests_per_minute == 10

    def test_custom_default_rate(self) -> None:
        limiter = DomainRateLimiter(default_rate=RateConfig(requests_per_minute=99))
        assert limiter.get_config("unknown.com").requests_per_minute == 99


# ═══════════════════════════════════════════════════════════════════════
# No-op mode (no Redis)
# ═══════════════════════════════════════════════════════════════════════


class TestNoOpMode:
    """When redis_client is None, all operations should be no-ops."""

    def test_acquire_returns_true(self) -> None:
        limiter = DomainRateLimiter()
        assert limiter.acquire("amazon.com") is True

    def test_wait_for_slot_returns_zero(self) -> None:
        limiter = DomainRateLimiter()
        assert limiter.wait_for_slot("amazon.com") == 0.0

    def test_time_until_slot_returns_negative(self) -> None:
        limiter = DomainRateLimiter()
        assert limiter.time_until_slot("amazon.com") == -1.0

    def test_reset_does_not_error(self) -> None:
        limiter = DomainRateLimiter()
        limiter.reset("amazon.com")  # Should not raise


# ═══════════════════════════════════════════════════════════════════════
# DomainRateLimiter.acquire() with mock Redis
# ═══════════════════════════════════════════════════════════════════════


def _make_mock_redis(current_count: int = 0) -> MagicMock:
    """Create a mock Redis client for testing acquire()."""
    mock_redis = MagicMock()
    mock_pipe = MagicMock()

    # Pipeline execute returns: [removed_count, count_before_zadd, zadd_result, expire_result]
    mock_pipe.execute.return_value = [0, current_count, 1, True]
    mock_redis.pipeline.return_value = mock_pipe

    return mock_redis


class TestAcquire:
    """Test acquire() with mock Redis pipeline."""

    def test_under_limit_returns_true(self) -> None:
        mock_redis = _make_mock_redis(current_count=3)
        limiter = DomainRateLimiter(mock_redis)
        assert limiter.acquire("amazon.com") is True

    def test_at_limit_returns_false(self) -> None:
        mock_redis = _make_mock_redis(current_count=10)  # amazon.com limit = 10
        limiter = DomainRateLimiter(mock_redis)
        assert limiter.acquire("amazon.com") is False

    def test_over_limit_removes_entry(self) -> None:
        """When over limit, the entry we just added should be removed."""
        mock_redis = _make_mock_redis(current_count=10)
        limiter = DomainRateLimiter(mock_redis)
        limiter.acquire("amazon.com")
        # Verify zrem was called
        mock_redis.zrem.assert_called_once()

    def test_under_limit_does_not_remove(self) -> None:
        mock_redis = _make_mock_redis(current_count=3)
        limiter = DomainRateLimiter(mock_redis)
        limiter.acquire("amazon.com")
        mock_redis.zrem.assert_not_called()

    def test_pipeline_commands_called(self) -> None:
        mock_redis = _make_mock_redis(current_count=0)
        pipe = mock_redis.pipeline.return_value
        limiter = DomainRateLimiter(mock_redis)
        limiter.acquire("amazon.com")

        # Verify pipeline was used with transaction=True
        mock_redis.pipeline.assert_called_once_with(transaction=True)
        # Verify commands were called on the pipeline
        pipe.zremrangebyscore.assert_called_once()
        pipe.zcard.assert_called_once()
        pipe.zadd.assert_called_once()
        pipe.expire.assert_called_once()
        pipe.execute.assert_called_once()

    def test_redis_key_format(self) -> None:
        mock_redis = _make_mock_redis(current_count=0)
        pipe = mock_redis.pipeline.return_value
        limiter = DomainRateLimiter(mock_redis)
        limiter.acquire("target.com")

        key_arg = pipe.zcard.call_args[0][0]
        assert key_arg == "rate_limit:target.com"


# ═══════════════════════════════════════════════════════════════════════
# time_until_slot() tests
# ═══════════════════════════════════════════════════════════════════════


class TestTimeUntilSlot:
    """Test time_until_slot() with mock Redis."""

    def test_slot_available(self) -> None:
        mock_redis = MagicMock()
        mock_redis.zcard.return_value = 3  # Under limit
        limiter = DomainRateLimiter(mock_redis)
        assert limiter.time_until_slot("amazon.com") == 0.0

    def test_slot_not_available(self) -> None:
        now = time.time()
        mock_redis = MagicMock()
        mock_redis.zcard.return_value = 10  # At limit
        # Oldest entry is 50 seconds ago → slot opens in 10 seconds
        mock_redis.zrange.return_value = [(b"entry", now - 50)]
        limiter = DomainRateLimiter(mock_redis)
        wait = limiter.time_until_slot("amazon.com")
        # Should be ~10 seconds (60 - 50)
        assert 9.0 <= wait <= 11.0

    def test_no_entries(self) -> None:
        mock_redis = MagicMock()
        mock_redis.zcard.return_value = 10
        mock_redis.zrange.return_value = []
        limiter = DomainRateLimiter(mock_redis)
        assert limiter.time_until_slot("amazon.com") == 0.0


# ═══════════════════════════════════════════════════════════════════════
# wait_for_slot() tests
# ═══════════════════════════════════════════════════════════════════════


class TestWaitForSlot:
    """Test wait_for_slot() blocking behaviour."""

    def test_slot_available_immediately(self) -> None:
        """When under limit, should return 0.0 without sleeping."""
        mock_redis = _make_mock_redis(current_count=0)
        limiter = DomainRateLimiter(mock_redis)
        waited = limiter.wait_for_slot("amazon.com")
        assert waited == 0.0

    @patch("price_radar.application.rate_limiter.time.sleep")
    def test_waits_then_acquires(self, mock_sleep: MagicMock) -> None:
        """Should sleep and retry when initially over limit."""
        mock_redis = _make_mock_redis(current_count=10)
        pipe = mock_redis.pipeline.return_value

        # First call: over limit; second call: under limit
        pipe.execute.side_effect = [
            [0, 10, 1, True],  # over limit
            [0, 5, 1, True],   # under limit
        ]
        mock_redis.zcard.return_value = 10
        mock_redis.zrange.return_value = [(b"e", time.time() - 55)]  # ~5s wait

        limiter = DomainRateLimiter(mock_redis)
        waited = limiter.wait_for_slot("amazon.com", max_wait=30.0)

        assert waited > 0
        assert mock_sleep.called

    def test_raises_when_max_wait_exceeded(self) -> None:
        """Should raise RateLimitExceeded when waiting would exceed max_wait."""
        mock_redis = _make_mock_redis(current_count=10)

        # Always over limit, slot opens in 120s
        mock_redis.zcard.return_value = 10
        mock_redis.zrange.return_value = [(b"e", time.time() - 1)]

        limiter = DomainRateLimiter(mock_redis)
        with pytest.raises(RateLimitExceeded) as exc_info:
            limiter.wait_for_slot("amazon.com", max_wait=5.0)

        assert exc_info.value.domain == "amazon.com"
        assert exc_info.value.max_wait == 5.0


# ═══════════════════════════════════════════════════════════════════════
# RateLimitExceeded exception tests
# ═══════════════════════════════════════════════════════════════════════


class TestRateLimitExceeded:
    """Test the custom exception."""

    def test_attributes(self) -> None:
        exc = RateLimitExceeded(domain="target.com", wait_needed=45.0, max_wait=30.0)
        assert exc.domain == "target.com"
        assert exc.wait_needed == 45.0
        assert exc.max_wait == 30.0

    def test_message(self) -> None:
        exc = RateLimitExceeded(domain="etsy.com", wait_needed=10.5, max_wait=5.0)
        assert "etsy.com" in str(exc)
        assert "10.5" in str(exc)


# ═══════════════════════════════════════════════════════════════════════
# reset() tests
# ═══════════════════════════════════════════════════════════════════════


class TestReset:
    """Test reset() clears rate limit data."""

    def test_reset_calls_delete(self) -> None:
        mock_redis = MagicMock()
        limiter = DomainRateLimiter(mock_redis)
        limiter.reset("amazon.com")
        mock_redis.delete.assert_called_once_with("rate_limit:amazon.com")


# ═══════════════════════════════════════════════════════════════════════
# DEFAULT_RATE_LIMITS sanity checks
# ═══════════════════════════════════════════════════════════════════════


class TestDefaults:
    """Verify the default rate limit table."""

    def test_known_domains_present(self) -> None:
        assert "amazon.com" in DEFAULT_RATE_LIMITS
        assert "target.com" in DEFAULT_RATE_LIMITS
        assert "etsy.com" in DEFAULT_RATE_LIMITS
        assert "bestbuy.com" in DEFAULT_RATE_LIMITS

    def test_aggressive_sites_are_stricter(self) -> None:
        amazon = DEFAULT_RATE_LIMITS["amazon.com"]
        etsy = DEFAULT_RATE_LIMITS["etsy.com"]
        assert etsy.requests_per_minute < amazon.requests_per_minute

    def test_default_unknown_rate(self) -> None:
        assert DEFAULT_UNKNOWN_RATE.requests_per_minute == 5

    def test_all_configs_have_positive_limits(self) -> None:
        for domain, config in DEFAULT_RATE_LIMITS.items():
            assert config.requests_per_minute > 0, f"{domain} has non-positive limit"
            assert config.window_seconds > 0, f"{domain} has non-positive window"


# ═══════════════════════════════════════════════════════════════════════
# PageFetcher integration — rate limiter called before fetch
# ═══════════════════════════════════════════════════════════════════════


class TestPageFetcherRateLimitIntegration:
    """Test that PageFetcher calls rate limiter before making requests."""

    @patch("price_radar.application.price_extraction.fetcher.httpx.get")
    def test_fetch_calls_rate_limiter(self, mock_httpx_get: MagicMock) -> None:
        """fetch() should call wait_for_slot before httpx request."""
        from price_radar.application.price_extraction.fetcher import PageFetcher

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html>" + "x" * 600 + "</html>"
        mock_response.raise_for_status = MagicMock()
        mock_httpx_get.return_value = mock_response

        mock_limiter = MagicMock(spec=DomainRateLimiter)
        mock_limiter.wait_for_slot.return_value = 0.0

        fetcher = PageFetcher(
            use_playwright=False,
            rate_limiter=mock_limiter,
        )
        fetcher.fetch("https://www.amazon.com/dp/B0X")

        mock_limiter.wait_for_slot.assert_called_once_with(
            "amazon.com", max_wait=120.0,
        )

    @patch("price_radar.application.price_extraction.fetcher.httpx.get")
    def test_fetch_and_extract_calls_rate_limiter(self, mock_httpx_get: MagicMock) -> None:
        """fetch_and_extract() should call wait_for_slot before fetching."""
        from price_radar.application.price_extraction.fetcher import PageFetcher

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html>" + "x" * 600 + "</html>"
        mock_response.raise_for_status = MagicMock()
        mock_httpx_get.return_value = mock_response

        mock_limiter = MagicMock(spec=DomainRateLimiter)
        mock_limiter.wait_for_slot.return_value = 0.0

        fetcher = PageFetcher(
            use_playwright=False,
            rate_limiter=mock_limiter,
        )
        fetcher.fetch_and_extract("https://www.ebay.com/itm/123")

        mock_limiter.wait_for_slot.assert_called_once_with(
            "ebay.com", max_wait=120.0,
        )

    def test_fetch_without_rate_limiter(self) -> None:
        """When no rate_limiter is set, fetch should still work."""
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

    @patch("price_radar.application.price_extraction.fetcher.httpx.get")
    def test_rate_limit_exceeded_propagates(self, mock_httpx_get: MagicMock) -> None:
        """RateLimitExceeded from wait_for_slot should propagate to caller."""
        from price_radar.application.price_extraction.fetcher import PageFetcher

        mock_limiter = MagicMock(spec=DomainRateLimiter)
        mock_limiter.wait_for_slot.side_effect = RateLimitExceeded(
            domain="target.com", wait_needed=120.0, max_wait=60.0,
        )

        fetcher = PageFetcher(
            use_playwright=False,
            rate_limiter=mock_limiter,
        )

        with pytest.raises(RateLimitExceeded):
            fetcher.fetch("https://www.target.com/p/foo")

        # httpx should NOT have been called
        mock_httpx_get.assert_not_called()

    @patch("price_radar.application.price_extraction.fetcher.httpx.get")
    def test_custom_max_wait(self, mock_httpx_get: MagicMock) -> None:
        """rate_limit_max_wait should be passed to wait_for_slot."""
        from price_radar.application.price_extraction.fetcher import PageFetcher

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html>" + "x" * 600 + "</html>"
        mock_response.raise_for_status = MagicMock()
        mock_httpx_get.return_value = mock_response

        mock_limiter = MagicMock(spec=DomainRateLimiter)
        mock_limiter.wait_for_slot.return_value = 0.0

        fetcher = PageFetcher(
            use_playwright=False,
            rate_limiter=mock_limiter,
            rate_limit_max_wait=30.0,
        )
        fetcher.fetch("https://amazon.com/dp/B0X")

        mock_limiter.wait_for_slot.assert_called_once_with(
            "amazon.com", max_wait=30.0,
        )
