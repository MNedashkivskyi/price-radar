"""Tests for ScrapingService and scraping Celery tasks.

Tests cover:
1. ScrapingService.scrape_one() — success, failure, dedup, auto-fail after threshold
2. PricePoint deduplication logic
3. CompetitorProduct bookkeeping (consecutive_failures, fetch_strategy, status)
4. Error categorization
5. Alert evaluation integration
6. Dead-letter queue notifications

The tests mock the heavy infrastructure modules (config, database, models) that
require pydantic-settings, asyncpg, etc.  We only need ScrapingService's logic
here, not the real DB layer.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Pre-load mocks for the infrastructure chain so importing scraping_service
# does NOT pull in pydantic-settings / asyncpg / Celery.
# Chain: scraping_service → models → database → config → pydantic_settings
# ---------------------------------------------------------------------------
_fake_config = MagicMock()
_fake_database = MagicMock()
_fake_models = MagicMock()

sys.modules.setdefault("pydantic_settings", MagicMock())
sys.modules.setdefault("asyncpg", MagicMock())
sys.modules.setdefault("price_radar.infrastructure.config", _fake_config)
sys.modules.setdefault("price_radar.infrastructure.database", _fake_database)
sys.modules.setdefault("price_radar.infrastructure.models", _fake_models)

from price_radar.application.price_extraction.fetcher import FetchResult
from price_radar.application.price_extraction.result import ExtractionResult
from price_radar.application.scrape_errors import ScrapeErrorCategory, categorize_error
from price_radar.application.scraping_service import (
    DOMAIN_SCRAPE_TIMEOUT,
    MAX_CONSECUTIVE_FAILURES,
    ScrapingService,
    ScrapeResult,
)


# ═══════════════════════════════════════════════════════════════════════
# Fixtures — lightweight fakes for DB models
# ═══════════════════════════════════════════════════════════════════════


def _make_competitor_product(**overrides: Any) -> MagicMock:
    """Create a fake CompetitorProduct with sensible defaults."""
    cp = MagicMock()
    cp.id = overrides.get("id", 1)
    cp.url = overrides.get("url", "https://www.amazon.com/dp/B0CHWRXH8B")
    cp.status = overrides.get("status", "active")
    cp.last_scraped_at = overrides.get("last_scraped_at", None)
    cp.last_success_at = overrides.get("last_success_at", None)
    cp.last_price = overrides.get("last_price", None)
    cp.consecutive_failures = overrides.get("consecutive_failures", 0)
    cp.fetch_strategy = overrides.get("fetch_strategy", None)
    cp.competitor_id = overrides.get("competitor_id", 10)
    cp.product_id = overrides.get("product_id", 20)
    return cp


def _make_price_point(**overrides: Any) -> MagicMock:
    """Create a fake PricePoint with sensible defaults."""
    pp = MagicMock()
    pp.price = overrides.get("price", 29.99)
    pp.currency = overrides.get("currency", "USD")
    pp.in_stock = overrides.get("in_stock", True)
    pp.scraped_at = overrides.get("scraped_at", datetime(2026, 2, 17, tzinfo=timezone.utc))
    return pp


def _make_fetch_result(*, success: bool = True, method: str = "httpx", error: str | None = None) -> FetchResult:
    """Create a FetchResult."""
    if success:
        return FetchResult(
            url="https://example.com",
            html="<html>" + "x" * 600 + "</html>",
            method=method,
            status_code=200,
            fetch_time=1.5,
            html_size=610,
        )
    return FetchResult(
        url="https://example.com",
        method=method,
        error=error or "http_403",
        status_code=403,
        fetch_time=0.5,
        html_size=0,
    )


def _make_extraction(*, success: bool = True) -> ExtractionResult:
    """Create an ExtractionResult."""
    if success:
        return ExtractionResult(
            current_price=Decimal("29.99"),
            original_price=Decimal("39.99"),
            currency="USD",
            in_stock=True,
            confidence=0.95,
            strategies_used=["json_ld", "css_selector"],
            all_results=[],
        )
    return ExtractionResult(confidence=0.0, all_results=[])


# ═══════════════════════════════════════════════════════════════════════
# ScrapingService.scrape_one() tests
# ═══════════════════════════════════════════════════════════════════════


def _make_service(
    db: AsyncMock,
    fetcher: MagicMock,
    cp: MagicMock | None,
    latest_pp: MagicMock | None = None,
) -> ScrapingService:
    """Create a ScrapingService with mocked DB helpers."""
    service = ScrapingService(db, fetcher=fetcher)
    # Patch internal DB methods to avoid real SQLAlchemy queries
    service._load_competitor_product = AsyncMock(return_value=cp)  # type: ignore[method-assign]
    service._get_latest_price_point = AsyncMock(return_value=latest_pp)  # type: ignore[method-assign]
    # Patch alert evaluation to avoid DB queries
    service._evaluate_alerts = AsyncMock(return_value=0)  # type: ignore[method-assign]
    service._notify_dlq_entry = AsyncMock()  # type: ignore[method-assign]
    return service


class TestScrapeOneSuccess:
    """Test successful scraping scenarios."""

    @pytest.mark.asyncio
    async def test_scrape_success_inserts_price_point(self) -> None:
        """Successful scrape should insert a PricePoint and update CP."""
        cp = _make_competitor_product()
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        fetcher = MagicMock()
        fetcher.fetch_and_extract.return_value = (
            _make_fetch_result(success=True),
            _make_extraction(success=True),
        )

        service = _make_service(db, fetcher, cp=cp, latest_pp=None)
        result = await service.scrape_one(1)

        assert result.success is True
        assert result.price == Decimal("29.99")
        assert result.currency == "USD"
        assert result.in_stock is True
        assert result.fetch_method == "httpx"
        assert result.was_deduplicated is False
        assert result.confidence == 0.95
        assert result.strategies_used == ["json_ld", "css_selector"]

        # PricePoint added + CompetitorProduct updated
        assert db.add.call_count == 2  # PricePoint + CP
        assert db.commit.called

    @pytest.mark.asyncio
    async def test_scrape_success_updates_cp_bookkeeping(self) -> None:
        """Successful scrape should reset failures, set fetch_strategy, etc."""
        cp = _make_competitor_product(consecutive_failures=2, fetch_strategy="httpx")
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        fetcher = MagicMock()
        fetcher.fetch_and_extract.return_value = (
            _make_fetch_result(success=True, method="playwright"),
            _make_extraction(success=True),
        )

        service = _make_service(db, fetcher, cp=cp, latest_pp=None)
        await service.scrape_one(1)

        # Verify CP updated
        assert cp.consecutive_failures == 0
        assert cp.fetch_strategy == "playwright"
        assert cp.last_price == 29.99
        assert cp.last_scraped_at is not None
        assert cp.last_success_at is not None

    @pytest.mark.asyncio
    async def test_scrape_recovers_failed_status(self) -> None:
        """A successful scrape on a 'failed' CP should set status back to 'active'."""
        cp = _make_competitor_product(
            status="failed",
            consecutive_failures=MAX_CONSECUTIVE_FAILURES,
        )
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        fetcher = MagicMock()
        fetcher.fetch_and_extract.return_value = (
            _make_fetch_result(success=True),
            _make_extraction(success=True),
        )

        service = _make_service(db, fetcher, cp=cp, latest_pp=None)
        result = await service.scrape_one(1)

        assert result.success is True
        assert cp.status == "active"
        assert cp.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_scrape_success_calls_evaluate_alerts(self) -> None:
        """Successful scrape with price change should evaluate alert rules."""
        cp = _make_competitor_product()
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        fetcher = MagicMock()
        fetcher.fetch_and_extract.return_value = (
            _make_fetch_result(success=True),
            _make_extraction(success=True),
        )

        service = _make_service(db, fetcher, cp=cp, latest_pp=None)
        service._evaluate_alerts = AsyncMock(return_value=2)  # type: ignore[method-assign]
        result = await service.scrape_one(1)

        assert result.success is True
        assert result.alerts_fired == 2
        service._evaluate_alerts.assert_called_once()

    @pytest.mark.asyncio
    async def test_scrape_dedup_skips_alert_evaluation(self) -> None:
        """When price is unchanged (deduplicated), alerts should not be evaluated."""
        cp = _make_competitor_product(last_price=29.99)
        existing_pp = _make_price_point(price=29.99, currency="USD", in_stock=True)

        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        fetcher = MagicMock()
        fetcher.fetch_and_extract.return_value = (
            _make_fetch_result(success=True),
            _make_extraction(success=True),
        )

        service = _make_service(db, fetcher, cp=cp, latest_pp=existing_pp)
        service._evaluate_alerts = AsyncMock(return_value=0)  # type: ignore[method-assign]
        result = await service.scrape_one(1)

        assert result.success is True
        assert result.was_deduplicated is True
        assert result.alerts_fired == 0
        service._evaluate_alerts.assert_not_called()


class TestScrapeOneFailure:
    """Test failure scenarios."""

    @pytest.mark.asyncio
    async def test_not_found_returns_error(self) -> None:
        """Scraping a non-existent CP returns an error."""
        db = AsyncMock()
        fetcher = MagicMock()

        service = _make_service(db, fetcher, cp=None)
        result = await service.scrape_one(999)

        assert result.success is False
        assert result.error == "competitor_product_not_found"

    @pytest.mark.asyncio
    async def test_paused_cp_returns_error(self) -> None:
        """Scraping a paused CP returns an error without fetching."""
        cp = _make_competitor_product(status="paused")
        db = AsyncMock()
        fetcher = MagicMock()

        service = _make_service(db, fetcher, cp=cp)
        result = await service.scrape_one(1)

        assert result.success is False
        assert result.error == "competitor_product_paused"

    @pytest.mark.asyncio
    async def test_fetch_failure_increments_consecutive_failures(self) -> None:
        """Failed fetch should increment consecutive_failures on CP."""
        cp = _make_competitor_product(consecutive_failures=1)
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        fetcher = MagicMock()
        fetcher.fetch_and_extract.return_value = (
            _make_fetch_result(success=False),
            _make_extraction(success=False),
        )

        service = _make_service(db, fetcher, cp=cp)
        result = await service.scrape_one(1)

        assert result.success is False
        assert cp.consecutive_failures == 2
        assert cp.status == "active"  # Not yet at threshold (3)

    @pytest.mark.asyncio
    async def test_marks_failed_after_threshold(self) -> None:
        """After MAX_CONSECUTIVE_FAILURES, CP status → 'failed'."""
        cp = _make_competitor_product(
            consecutive_failures=MAX_CONSECUTIVE_FAILURES - 1
        )
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        fetcher = MagicMock()
        fetcher.fetch_and_extract.return_value = (
            _make_fetch_result(success=False),
            _make_extraction(success=False),
        )

        service = _make_service(db, fetcher, cp=cp)
        result = await service.scrape_one(1)

        assert result.success is False
        assert cp.consecutive_failures == MAX_CONSECUTIVE_FAILURES
        assert cp.status == "failed"

    @pytest.mark.asyncio
    async def test_dlq_notification_sent_on_failure_threshold(self) -> None:
        """When CP reaches failure threshold, DLQ notification should be sent."""
        cp = _make_competitor_product(
            consecutive_failures=MAX_CONSECUTIVE_FAILURES - 1
        )
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        fetcher = MagicMock()
        fetcher.fetch_and_extract.return_value = (
            _make_fetch_result(success=False),
            _make_extraction(success=False),
        )

        service = _make_service(db, fetcher, cp=cp)
        result = await service.scrape_one(1)

        assert result.success is False
        assert cp.status == "failed"
        service._notify_dlq_entry.assert_called_once()

    @pytest.mark.asyncio
    async def test_extraction_failure_records_failure(self) -> None:
        """Fetch succeeds but extraction fails → still a failure."""
        cp = _make_competitor_product()
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        fetcher = MagicMock()
        fetcher.fetch_and_extract.return_value = (
            _make_fetch_result(success=True),
            _make_extraction(success=False),
        )

        service = _make_service(db, fetcher, cp=cp)
        result = await service.scrape_one(1)

        assert result.success is False
        assert result.error == "extraction_failed"
        assert result.error_category == ScrapeErrorCategory.PARSE_FAILED
        assert cp.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_failure_includes_error_category(self) -> None:
        """Failed scrape should include the error_category field."""
        cp = _make_competitor_product()
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        fetcher = MagicMock()
        fetcher.fetch_and_extract.return_value = (
            _make_fetch_result(success=False, error="captcha_detected"),
            _make_extraction(success=False),
        )

        service = _make_service(db, fetcher, cp=cp)
        result = await service.scrape_one(1)

        assert result.success is False
        assert result.error_category == ScrapeErrorCategory.CAPTCHA

    @pytest.mark.asyncio
    async def test_unexpected_exception_records_failure(self) -> None:
        """Unexpected exception in fetcher → failure recorded gracefully."""
        cp = _make_competitor_product()
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        fetcher = MagicMock()
        fetcher.fetch_and_extract.side_effect = RuntimeError("browser crashed")

        service = _make_service(db, fetcher, cp=cp)
        result = await service.scrape_one(1)

        assert result.success is False
        assert "RuntimeError" in result.error
        assert cp.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_domain_scrape_timeout_logs_error_and_records_failure(self) -> None:
        """When fetch_and_extract exceeds DOMAIN_SCRAPE_TIMEOUT, log error and fail."""
        import asyncio as _asyncio

        cp = _make_competitor_product()
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        fetcher = MagicMock()

        service = _make_service(db, fetcher, cp=cp)

        with patch(
            "price_radar.application.scraping_service.asyncio.wait_for",
            side_effect=_asyncio.TimeoutError,
        ):
            result = await service.scrape_one(1)

        assert result.success is False
        assert result.error == f"domain_scrape_timeout:{DOMAIN_SCRAPE_TIMEOUT}s"
        assert result.error_category == ScrapeErrorCategory.TIMEOUT
        assert cp.consecutive_failures == 1


# ═══════════════════════════════════════════════════════════════════════
# Deduplication tests
# ═══════════════════════════════════════════════════════════════════════


class TestDeduplication:
    """Test PricePoint deduplication logic."""

    def test_no_previous_price_point_not_duplicate(self) -> None:
        """First scrape (no previous PricePoint) is never a duplicate."""
        assert ScrapingService._is_duplicate(None, Decimal("29.99"), "USD", True) is False

    def test_same_price_is_duplicate(self) -> None:
        """Same price/currency/in_stock → duplicate."""
        pp = _make_price_point(price=29.99, currency="USD", in_stock=True)
        assert ScrapingService._is_duplicate(pp, Decimal("29.99"), "USD", True) is True

    def test_different_price_not_duplicate(self) -> None:
        """Different price → not a duplicate."""
        pp = _make_price_point(price=29.99, currency="USD", in_stock=True)
        assert ScrapingService._is_duplicate(pp, Decimal("34.99"), "USD", True) is False

    def test_different_currency_not_duplicate(self) -> None:
        """Same price, different currency → not a duplicate."""
        pp = _make_price_point(price=29.99, currency="USD", in_stock=True)
        assert ScrapingService._is_duplicate(pp, Decimal("29.99"), "EUR", True) is False

    def test_different_stock_not_duplicate(self) -> None:
        """Same price, but stock changed → not a duplicate."""
        pp = _make_price_point(price=29.99, currency="USD", in_stock=True)
        assert ScrapingService._is_duplicate(pp, Decimal("29.99"), "USD", False) is False

    def test_none_price_not_duplicate(self) -> None:
        """None new price → never a duplicate."""
        pp = _make_price_point(price=29.99, currency="USD", in_stock=True)
        assert ScrapingService._is_duplicate(pp, None, "USD", True) is False

    def test_small_price_difference_is_duplicate(self) -> None:
        """Price difference < 0.005 should be considered duplicate (float rounding)."""
        pp = _make_price_point(price=29.99, currency="USD", in_stock=True)
        assert ScrapingService._is_duplicate(pp, Decimal("29.993"), "USD", True) is True

    def test_half_cent_difference_not_duplicate(self) -> None:
        """Price difference >= 0.005 is a real change."""
        pp = _make_price_point(price=29.99, currency="USD", in_stock=True)
        assert ScrapingService._is_duplicate(pp, Decimal("29.995"), "USD", True) is False

    @pytest.mark.asyncio
    async def test_dedup_skips_price_point_insert(self) -> None:
        """When price is unchanged, no new PricePoint should be added."""
        cp = _make_competitor_product(last_price=29.99)
        existing_pp = _make_price_point(price=29.99, currency="USD", in_stock=True)

        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        fetcher = MagicMock()
        fetcher.fetch_and_extract.return_value = (
            _make_fetch_result(success=True),
            _make_extraction(success=True),  # Same price: 29.99 USD
        )

        service = _make_service(db, fetcher, cp=cp, latest_pp=existing_pp)
        result = await service.scrape_one(1)

        assert result.success is True
        assert result.was_deduplicated is True

        # Only CP bookkeeping update (no PricePoint)
        assert db.add.call_count == 1  # Only CP, not PricePoint


# ═══════════════════════════════════════════════════════════════════════
# Error categorization tests
# ═══════════════════════════════════════════════════════════════════════


class TestErrorCategorization:
    """Test error string to category mapping."""

    def test_captcha_detected(self) -> None:
        assert categorize_error("captcha_detected") is ScrapeErrorCategory.CAPTCHA

    def test_circuit_open(self) -> None:
        assert categorize_error("circuit_open") is ScrapeErrorCategory.CIRCUIT_OPEN

    def test_rate_limited(self) -> None:
        assert categorize_error("rate_limited:example.com") is ScrapeErrorCategory.RATE_LIMITED

    def test_http_429(self) -> None:
        assert categorize_error("http_429") is ScrapeErrorCategory.RATE_LIMITED

    def test_timeout(self) -> None:
        assert categorize_error("domain_scrape_timeout:90s") is ScrapeErrorCategory.TIMEOUT

    def test_http_403(self) -> None:
        assert categorize_error("http_403") is ScrapeErrorCategory.BLOCKED

    def test_extraction_failed(self) -> None:
        assert categorize_error("extraction_failed") is ScrapeErrorCategory.PARSE_FAILED

    def test_extraction_found_no_price(self) -> None:
        assert categorize_error("extraction_found_no_price") is ScrapeErrorCategory.PARSE_FAILED

    def test_connection_error(self) -> None:
        assert categorize_error("request_error: ConnectError") is ScrapeErrorCategory.SITE_DOWN

    def test_http_500(self) -> None:
        assert categorize_error("http_500") is ScrapeErrorCategory.SITE_DOWN

    def test_playwright_protocol_error(self) -> None:
        assert (
            categorize_error("playwright_error: Error: ERR_HTTP2_PROTOCOL_ERROR")
            is ScrapeErrorCategory.SITE_DOWN
        )

    def test_none_error(self) -> None:
        assert categorize_error(None) is ScrapeErrorCategory.UNKNOWN

    def test_unknown_error(self) -> None:
        assert categorize_error("some_random_thing") is ScrapeErrorCategory.UNKNOWN


# ═══════════════════════════════════════════════════════════════════════
# ScrapeResult dataclass tests
# ═══════════════════════════════════════════════════════════════════════


class TestScrapeResult:
    """Test ScrapeResult dataclass defaults and fields."""

    def test_default_values(self) -> None:
        """ScrapeResult should have sensible defaults."""
        r = ScrapeResult(competitor_product_id=1, success=False)
        assert r.price is None
        assert r.currency is None
        assert r.in_stock is None
        assert r.fetch_method == "none"
        assert r.was_deduplicated is False
        assert r.error is None
        assert r.error_category is None
        assert r.alerts_fired == 0

    def test_success_result(self) -> None:
        """ScrapeResult with all fields populated."""
        r = ScrapeResult(
            competitor_product_id=42,
            success=True,
            price=Decimal("19.99"),
            currency="EUR",
            in_stock=True,
            fetch_method="playwright",
            confidence=0.87,
            strategies_used=["json_ld"],
            alerts_fired=1,
        )
        assert r.success is True
        assert r.price == Decimal("19.99")
        assert r.fetch_method == "playwright"
        assert r.alerts_fired == 1


# ═══════════════════════════════════════════════════════════════════════
# Cooperative timeout tests
# ═══════════════════════════════════════════════════════════════════════


class TestCooperativeTimeout:
    """Test the cooperative (fetcher-side) timeout handling."""

    @pytest.mark.asyncio
    async def test_fetcher_domain_scrape_timeout_treated_as_failure(self) -> None:
        """When the fetcher itself returns domain_scrape_timeout, it is recorded as failure."""
        cp = _make_competitor_product()
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        fetcher = MagicMock()
        # Simulate the fetcher detecting the budget was exhausted
        fetcher.fetch_and_extract.return_value = (
            FetchResult(url=cp.url, error="domain_scrape_timeout"),
            ExtractionResult(confidence=0.0, all_results=[]),
        )

        service = _make_service(db, fetcher, cp=cp)
        result = await service.scrape_one(1)

        assert result.success is False
        assert result.error == f"domain_scrape_timeout:{DOMAIN_SCRAPE_TIMEOUT}s"
        assert cp.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_cooperative_timeout_marks_cp_failed_after_threshold(self) -> None:
        """Cooperative timeout should increment consecutive_failures and mark failed."""
        cp = _make_competitor_product(consecutive_failures=MAX_CONSECUTIVE_FAILURES - 1)
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        fetcher = MagicMock()
        fetcher.fetch_and_extract.return_value = (
            FetchResult(url=cp.url, error="domain_scrape_timeout"),
            ExtractionResult(confidence=0.0, all_results=[]),
        )

        service = _make_service(db, fetcher, cp=cp)
        result = await service.scrape_one(1)

        assert result.success is False
        assert cp.consecutive_failures == MAX_CONSECUTIVE_FAILURES
        assert cp.status == "failed"

    @pytest.mark.asyncio
    async def test_asyncio_timeout_still_works_as_safety_net(self) -> None:
        """asyncio.wait_for should still catch threads that exceed the budget."""
        import asyncio as _asyncio

        cp = _make_competitor_product()
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        fetcher = MagicMock()

        service = _make_service(db, fetcher, cp=cp)

        with patch(
            "price_radar.application.scraping_service.asyncio.wait_for",
            side_effect=_asyncio.TimeoutError,
        ):
            result = await service.scrape_one(1)

        assert result.success is False
        assert "domain_scrape_timeout" in result.error
        assert cp.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_domain_scrape_timeout_value_is_90(self) -> None:
        """The DOMAIN_SCRAPE_TIMEOUT constant should be 90 seconds."""
        assert DOMAIN_SCRAPE_TIMEOUT == 90


class TestConstants:
    """Test module-level constants."""

    def test_max_consecutive_failures_is_3(self) -> None:
        """The failure threshold should be 3 (alert shop owner after 3 failures)."""
        assert MAX_CONSECUTIVE_FAILURES == 3
