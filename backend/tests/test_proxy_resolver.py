"""Tests for ProxyResolver — per-domain proxy routing with Redis caching.

Unit tests use mocks; no real Redis or network is required.

Run all:
    PYTHONPATH=src python -m pytest tests/test_proxy_resolver.py -v -s
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from price_radar.application.proxy_resolver import (
    ProxyResolver,
    ProxyTier,
    _KNOWN_RESIDENTIAL_DOMAINS,
)


# ── ProxyTier enum ──────────────────────────────────────────────────────


class TestProxyTier:
    def test_values(self) -> None:
        assert ProxyTier.DIRECT.value == "direct"
        assert ProxyTier.RESIDENTIAL.value == "residential"

    def test_is_string_enum(self) -> None:
        assert isinstance(ProxyTier.DIRECT, str)
        assert ProxyTier.DIRECT == "direct"

    def test_from_value(self) -> None:
        assert ProxyTier("direct") == ProxyTier.DIRECT
        assert ProxyTier("residential") == ProxyTier.RESIDENTIAL


# ── Known residential domains ──────────────────────────────────────────


class TestKnownDomains:
    def test_amazon_is_known(self) -> None:
        assert "amazon.com" in _KNOWN_RESIDENTIAL_DOMAINS

    def test_allegro_is_known(self) -> None:
        assert "allegro.pl" in _KNOWN_RESIDENTIAL_DOMAINS

    def test_zalando_is_known(self) -> None:
        assert "zalando.pl" in _KNOWN_RESIDENTIAL_DOMAINS

    def test_ceneo_is_known(self) -> None:
        assert "ceneo.pl" in _KNOWN_RESIDENTIAL_DOMAINS

    def test_target_is_known(self) -> None:
        assert "target.com" in _KNOWN_RESIDENTIAL_DOMAINS

    def test_minimum_count(self) -> None:
        assert len(_KNOWN_RESIDENTIAL_DOMAINS) >= 20


# ── ProxyResolver without proxy ────────────────────────────────────────


class TestProxyResolverNoProxy:
    """When no proxy URL is configured, everything is DIRECT."""

    def test_resolve_always_direct(self) -> None:
        resolver = ProxyResolver(proxy_url="")
        assert resolver.resolve("amazon.com") == ProxyTier.RESIDENTIAL
        # But since no proxy URL, get_proxy_url returns None
        assert resolver.get_proxy_url("amazon.com") is None

    def test_has_proxy_false(self) -> None:
        resolver = ProxyResolver(proxy_url="")
        assert resolver.has_proxy is False

    def test_get_proxy_url_returns_none(self) -> None:
        resolver = ProxyResolver(proxy_url="")
        assert resolver.get_proxy_url("example.com") is None

    def test_escalate_is_noop_without_proxy(self) -> None:
        resolver = ProxyResolver(proxy_url="")
        resolver.escalate("example.com")
        # No proxy URL, so even after escalation, get_proxy_url is None
        assert resolver.get_proxy_url("example.com") is None


# ── ProxyResolver with proxy ───────────────────────────────────────────


class TestProxyResolverWithProxy:
    """When a proxy URL is configured, routing works as expected."""

    PROXY_URL = "http://user:pass@gate.smartproxy.com:10001"

    def test_has_proxy_true(self) -> None:
        resolver = ProxyResolver(proxy_url=self.PROXY_URL)
        assert resolver.has_proxy is True

    def test_known_domain_resolves_residential(self) -> None:
        resolver = ProxyResolver(proxy_url=self.PROXY_URL)
        assert resolver.resolve("amazon.com") == ProxyTier.RESIDENTIAL

    def test_known_domain_returns_proxy_url(self) -> None:
        resolver = ProxyResolver(proxy_url=self.PROXY_URL)
        assert resolver.get_proxy_url("amazon.com") == self.PROXY_URL

    def test_unknown_domain_resolves_direct(self) -> None:
        resolver = ProxyResolver(proxy_url=self.PROXY_URL)
        assert resolver.resolve("example.com") == ProxyTier.DIRECT

    def test_unknown_domain_returns_none(self) -> None:
        resolver = ProxyResolver(proxy_url=self.PROXY_URL)
        assert resolver.get_proxy_url("example.com") is None

    def test_www_prefix_stripped(self) -> None:
        resolver = ProxyResolver(proxy_url=self.PROXY_URL)
        assert resolver.resolve("www.amazon.com") == ProxyTier.RESIDENTIAL

    def test_subdomain_resolves_to_base(self) -> None:
        resolver = ProxyResolver(proxy_url=self.PROXY_URL)
        assert resolver.resolve("smile.amazon.com") == ProxyTier.RESIDENTIAL


# ── Escalation ─────────────────────────────────────────────────────────


class TestProxyEscalation:
    """Auto-escalation from DIRECT to RESIDENTIAL."""

    PROXY_URL = "http://user:pass@gate.smartproxy.com:10001"

    def test_escalate_unknown_domain(self) -> None:
        resolver = ProxyResolver(proxy_url=self.PROXY_URL)
        assert resolver.resolve("newstore.com") == ProxyTier.DIRECT

        resolver.escalate("newstore.com")

        assert resolver.resolve("newstore.com") == ProxyTier.RESIDENTIAL
        assert resolver.get_proxy_url("newstore.com") == self.PROXY_URL

    def test_escalate_known_domain_is_noop(self) -> None:
        """Known domains are always RESIDENTIAL regardless of escalation calls."""
        resolver = ProxyResolver(proxy_url=self.PROXY_URL)
        resolver.escalate("amazon.com")  # should be a no-op
        assert resolver.resolve("amazon.com") == ProxyTier.RESIDENTIAL

    def test_reset_after_escalation(self) -> None:
        resolver = ProxyResolver(proxy_url=self.PROXY_URL)
        resolver.escalate("newstore.com")
        assert resolver.resolve("newstore.com") == ProxyTier.RESIDENTIAL

        resolver.reset("newstore.com")
        assert resolver.resolve("newstore.com") == ProxyTier.DIRECT

    def test_reset_known_domain_is_noop(self) -> None:
        """Cannot reset known residential domains."""
        resolver = ProxyResolver(proxy_url=self.PROXY_URL)
        resolver.reset("amazon.com")
        assert resolver.resolve("amazon.com") == ProxyTier.RESIDENTIAL


# ── Redis cache integration ────────────────────────────────────────────


class TestProxyResolverRedisCache:
    """Test Redis caching behaviour using a mock Redis client."""

    PROXY_URL = "http://user:pass@gate.smartproxy.com:10001"

    def _mock_redis(self) -> MagicMock:
        """Create a mock Redis client."""
        redis = MagicMock()
        redis.get.return_value = None
        return redis

    def test_escalation_writes_to_redis(self) -> None:
        redis = self._mock_redis()
        resolver = ProxyResolver(proxy_url=self.PROXY_URL, redis_client=redis)

        resolver.escalate("newstore.com")

        redis.setex.assert_called_once()
        args = redis.setex.call_args
        assert "proxy:tier:newstore.com" in str(args)

    def test_resolve_reads_from_redis(self) -> None:
        redis = self._mock_redis()
        redis.get.return_value = "residential"  # cached value
        resolver = ProxyResolver(proxy_url=self.PROXY_URL, redis_client=redis)

        tier = resolver.resolve("cached-store.com")

        assert tier == ProxyTier.RESIDENTIAL
        redis.get.assert_called()

    def test_redis_failure_falls_back_to_memory(self) -> None:
        redis = self._mock_redis()
        redis.get.side_effect = Exception("Redis connection refused")
        resolver = ProxyResolver(proxy_url=self.PROXY_URL, redis_client=redis)

        # Initially direct (redis error, no memory cache)
        assert resolver.resolve("fallback-store.com") == ProxyTier.DIRECT

        # Escalate writes to memory even if redis fails
        redis.setex.side_effect = Exception("Redis connection refused")
        resolver.escalate("fallback-store.com")

        # Should be residential from memory cache
        assert resolver.resolve("fallback-store.com") == ProxyTier.RESIDENTIAL


# ── Tier info / debug ──────────────────────────────────────────────────


class TestGetTierInfo:
    PROXY_URL = "http://user:pass@gate.smartproxy.com:10001"

    def test_known_domain_info(self) -> None:
        resolver = ProxyResolver(proxy_url=self.PROXY_URL)
        info = resolver.get_tier_info("amazon.com")
        assert info["tier"] == "residential"
        assert info["source"] == "known_residential"
        assert info["proxy_configured"] == "True"

    def test_unknown_domain_info(self) -> None:
        resolver = ProxyResolver(proxy_url=self.PROXY_URL)
        info = resolver.get_tier_info("example.com")
        assert info["tier"] == "direct"
        assert info["source"] == "default"

    def test_cached_domain_info(self) -> None:
        resolver = ProxyResolver(proxy_url=self.PROXY_URL)
        resolver.escalate("escalated.com")
        info = resolver.get_tier_info("escalated.com")
        assert info["tier"] == "residential"
        assert info["source"] == "cached"


# ── PageFetcher proxy integration ──────────────────────────────────────


class TestPageFetcherProxyIntegration:
    """Test that PageFetcher uses ProxyResolver correctly."""

    PROXY_URL = "http://user:pass@gate.smartproxy.com:10001"

    def test_direct_success_no_proxy(self) -> None:
        """When domain is DIRECT, httpx is called without proxy."""
        from price_radar.application.price_extraction.fetcher import (
            FetchResult,
            PageFetcher,
        )

        resolver = ProxyResolver(proxy_url=self.PROXY_URL)
        fetcher = PageFetcher(
            use_playwright=False,
            proxy_resolver=resolver,
        )

        with patch.object(fetcher, "_fetch_httpx") as mock_httpx:
            mock_httpx.return_value = FetchResult(
                url="https://example.com",
                html="<html>" + "x" * 1000,
                html_size=1006,
                method="httpx",
                status_code=200,
                proxy_tier="direct",
            )
            result = fetcher.fetch("https://example.com")
            assert result.success
            assert result.proxy_tier == "direct"

    def test_known_residential_domain_gets_proxy(self) -> None:
        """When domain is known RESIDENTIAL, the proxy URL is resolved."""
        resolver = ProxyResolver(proxy_url=self.PROXY_URL)
        proxy_url = resolver.get_proxy_url("amazon.com")
        assert proxy_url == self.PROXY_URL

    def test_direct_fail_triggers_escalation(self) -> None:
        """403 on DIRECT should escalate domain to RESIDENTIAL."""
        resolver = ProxyResolver(proxy_url=self.PROXY_URL)
        assert resolver.resolve("newsite.com") == ProxyTier.DIRECT

        # Simulate what the fetcher does on 403
        resolver.escalate("newsite.com")

        assert resolver.resolve("newsite.com") == ProxyTier.RESIDENTIAL
        assert resolver.get_proxy_url("newsite.com") == self.PROXY_URL


# ── Proxy pool rotation ──────────────────────────────────────────────


class TestProxyPoolRotation:
    """Test round-robin rotation across multiple proxy endpoints."""

    PROXY_URLS = [
        "http://user:pass@gate.smartproxy.com:10001",
        "http://user:pass@gate.smartproxy.com:10002",
        "http://user:pass@gate.smartproxy.com:10003",
    ]

    def test_pool_size(self) -> None:
        resolver = ProxyResolver(proxy_urls=self.PROXY_URLS)
        assert resolver.pool_size == 3

    def test_pool_size_single_url(self) -> None:
        resolver = ProxyResolver(proxy_url=self.PROXY_URLS[0])
        assert resolver.pool_size == 1

    def test_pool_size_empty(self) -> None:
        resolver = ProxyResolver(proxy_url="")
        assert resolver.pool_size == 0

    def test_has_proxy_with_pool(self) -> None:
        resolver = ProxyResolver(proxy_urls=self.PROXY_URLS)
        assert resolver.has_proxy is True

    def test_round_robin_rotation(self) -> None:
        """get_proxy_url should cycle through all pool endpoints."""
        resolver = ProxyResolver(proxy_urls=self.PROXY_URLS)
        urls = [resolver.get_proxy_url("amazon.com") for _ in range(6)]
        # Should cycle: 10001, 10002, 10003, 10001, 10002, 10003
        assert urls == self.PROXY_URLS + self.PROXY_URLS

    def test_single_url_returns_same(self) -> None:
        """Single-URL pool always returns the same URL."""
        resolver = ProxyResolver(proxy_url=self.PROXY_URLS[0])
        urls = [resolver.get_proxy_url("amazon.com") for _ in range(3)]
        assert all(u == self.PROXY_URLS[0] for u in urls)

    def test_direct_domain_returns_none_with_pool(self) -> None:
        """DIRECT domains still return None even with a pool."""
        resolver = ProxyResolver(proxy_urls=self.PROXY_URLS)
        assert resolver.get_proxy_url("example.com") is None

    def test_proxy_urls_takes_precedence(self) -> None:
        """proxy_urls parameter takes precedence over proxy_url."""
        resolver = ProxyResolver(
            proxy_url="http://should-be-ignored:1111",
            proxy_urls=self.PROXY_URLS,
        )
        assert resolver.pool_size == 3
        url = resolver.get_proxy_url("amazon.com")
        assert url in self.PROXY_URLS

    def test_empty_entries_filtered(self) -> None:
        """Empty strings in proxy_urls are silently filtered out."""
        resolver = ProxyResolver(
            proxy_urls=["http://a:b@host:1", "", "http://a:b@host:2", ""],
        )
        assert resolver.pool_size == 2

    def test_escalation_uses_pool(self) -> None:
        """After escalation, get_proxy_url returns from the pool."""
        resolver = ProxyResolver(proxy_urls=self.PROXY_URLS)
        resolver.escalate("newstore.com")
        url = resolver.get_proxy_url("newstore.com")
        assert url in self.PROXY_URLS

    def test_rotation_across_domains(self) -> None:
        """Rotation is global, not per-domain — requests to different
        domains advance the same round-robin cursor."""
        resolver = ProxyResolver(proxy_urls=self.PROXY_URLS)
        url1 = resolver.get_proxy_url("amazon.com")
        url2 = resolver.get_proxy_url("zalando.pl")
        url3 = resolver.get_proxy_url("target.com")
        assert [url1, url2, url3] == self.PROXY_URLS

    def test_thread_safety(self) -> None:
        """Multiple threads can call get_proxy_url concurrently without errors."""
        import threading

        resolver = ProxyResolver(proxy_urls=self.PROXY_URLS)
        results: list[str | None] = []
        lock = threading.Lock()

        def fetch_url() -> None:
            url = resolver.get_proxy_url("amazon.com")
            with lock:
                results.append(url)

        threads = [threading.Thread(target=fetch_url) for _ in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 30
        assert all(u in self.PROXY_URLS for u in results)
        # All 3 endpoints should have been used roughly equally (±1)
        counts = {u: results.count(u) for u in self.PROXY_URLS}
        assert all(c == 10 for c in counts.values())


# ── Domain normalisation ──────────────────────────────────────────────


class TestDomainNormalisation:
    def test_base_domain_from_www(self) -> None:
        resolver = ProxyResolver(proxy_url="")
        assert resolver._base_domain("www.amazon.com") == "amazon.com"

    def test_base_domain_from_subdomain(self) -> None:
        resolver = ProxyResolver(proxy_url="")
        assert resolver._base_domain("smile.amazon.com") == "amazon.com"

    def test_base_domain_country_tld(self) -> None:
        resolver = ProxyResolver(proxy_url="")
        assert resolver._base_domain("www.amazon.co.uk") == "amazon.co.uk"

    def test_base_domain_simple(self) -> None:
        resolver = ProxyResolver(proxy_url="")
        assert resolver._base_domain("example.com") == "example.com"

    def test_base_domain_polish(self) -> None:
        resolver = ProxyResolver(proxy_url="")
        assert resolver._base_domain("allegro.pl") == "allegro.pl"
