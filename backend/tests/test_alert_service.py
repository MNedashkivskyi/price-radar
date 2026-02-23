"""Tests for AlertService — alert rule evaluation and notification delivery.

Tests cover:
1. Rule evaluation logic (undercut, price_change, stock_change)
2. Alert event creation
3. DLQ failure notification
"""

from __future__ import annotations

import sys
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Pre-load mocks so imports don't pull in pydantic-settings / asyncpg
sys.modules.setdefault("pydantic_settings", MagicMock())
sys.modules.setdefault("asyncpg", MagicMock())
sys.modules.setdefault("price_radar.infrastructure.config", MagicMock())
sys.modules.setdefault("price_radar.infrastructure.database", MagicMock())
sys.modules.setdefault("price_radar.infrastructure.models", MagicMock())

from price_radar.application.alert_service import AlertService


def _make_rule(**overrides: Any) -> MagicMock:
    """Create a fake AlertRule."""
    rule = MagicMock()
    rule.id = overrides.get("id", 1)
    rule.type = overrides.get("type", "price_change")
    rule.threshold_pct = overrides.get("threshold_pct", 5.0)
    rule.channels = overrides.get("channels", {})
    rule.enabled = overrides.get("enabled", True)
    return rule


def _make_cp(**overrides: Any) -> MagicMock:
    """Create a fake CompetitorProduct."""
    cp = MagicMock()
    cp.id = overrides.get("id", 1)
    cp.url = overrides.get("url", "https://www.example.com/product")
    cp.competitor_id = overrides.get("competitor_id", 10)
    cp.product_id = overrides.get("product_id", 20)
    cp.consecutive_failures = overrides.get("consecutive_failures", 3)
    return cp


# ═══════════════════════════════════════════════════════════════════════
# Rule evaluation tests
# ═══════════════════════════════════════════════════════════════════════


class TestCheckRule:
    """Test AlertService._check_rule() for each rule type."""

    def test_undercut_triggers_when_below_threshold(self) -> None:
        """Competitor price below (our_price * (1 - threshold%)) triggers undercut."""
        rule = _make_rule(type="undercut", threshold_pct=10.0)
        result = AlertService._check_rule(
            rule,
            old_price=Decimal("100"),
            new_price=Decimal("85"),  # 15% below $100, threshold is 10%
            our_price=Decimal("100"),
            in_stock=True,
            old_in_stock=True,
        )
        assert result is True

    def test_undercut_does_not_trigger_above_threshold(self) -> None:
        """Competitor price above threshold does not trigger undercut."""
        rule = _make_rule(type="undercut", threshold_pct=10.0)
        result = AlertService._check_rule(
            rule,
            old_price=Decimal("100"),
            new_price=Decimal("95"),  # 5% below $100, threshold is 10%
            our_price=Decimal("100"),
            in_stock=True,
            old_in_stock=True,
        )
        assert result is False

    def test_undercut_no_our_price(self) -> None:
        """Undercut with no our_price should not trigger."""
        rule = _make_rule(type="undercut", threshold_pct=10.0)
        result = AlertService._check_rule(
            rule,
            old_price=Decimal("100"),
            new_price=Decimal("50"),
            our_price=None,
            in_stock=True,
            old_in_stock=True,
        )
        assert result is False

    def test_price_change_triggers_above_threshold(self) -> None:
        """Price change exceeding threshold % triggers alert."""
        rule = _make_rule(type="price_change", threshold_pct=5.0)
        result = AlertService._check_rule(
            rule,
            old_price=Decimal("100"),
            new_price=Decimal("90"),  # 10% change, threshold is 5%
            our_price=Decimal("100"),
            in_stock=True,
            old_in_stock=True,
        )
        assert result is True

    def test_price_change_does_not_trigger_below_threshold(self) -> None:
        """Price change below threshold % does not trigger."""
        rule = _make_rule(type="price_change", threshold_pct=10.0)
        result = AlertService._check_rule(
            rule,
            old_price=Decimal("100"),
            new_price=Decimal("95"),  # 5% change, threshold is 10%
            our_price=Decimal("100"),
            in_stock=True,
            old_in_stock=True,
        )
        assert result is False

    def test_price_change_no_old_price(self) -> None:
        """Price change with no old_price (first scrape) should not trigger."""
        rule = _make_rule(type="price_change", threshold_pct=5.0)
        result = AlertService._check_rule(
            rule,
            old_price=None,
            new_price=Decimal("90"),
            our_price=Decimal("100"),
            in_stock=True,
            old_in_stock=True,
        )
        assert result is False

    def test_stock_change_triggers(self) -> None:
        """Stock status change triggers alert."""
        rule = _make_rule(type="stock_change")
        result = AlertService._check_rule(
            rule,
            old_price=Decimal("100"),
            new_price=Decimal("100"),
            our_price=Decimal("100"),
            in_stock=False,
            old_in_stock=True,
        )
        assert result is True

    def test_stock_change_no_change(self) -> None:
        """Same stock status does not trigger."""
        rule = _make_rule(type="stock_change")
        result = AlertService._check_rule(
            rule,
            old_price=Decimal("100"),
            new_price=Decimal("100"),
            our_price=Decimal("100"),
            in_stock=True,
            old_in_stock=True,
        )
        assert result is False

    def test_stock_change_no_old_in_stock(self) -> None:
        """Stock change with no previous data should not trigger."""
        rule = _make_rule(type="stock_change")
        result = AlertService._check_rule(
            rule,
            old_price=Decimal("100"),
            new_price=Decimal("100"),
            our_price=Decimal("100"),
            in_stock=True,
            old_in_stock=None,
        )
        assert result is False

    def test_unknown_rule_type(self) -> None:
        """Unknown rule type should not trigger."""
        rule = _make_rule(type="unknown_type")
        result = AlertService._check_rule(
            rule,
            old_price=Decimal("100"),
            new_price=Decimal("50"),
            our_price=Decimal("100"),
            in_stock=True,
            old_in_stock=True,
        )
        assert result is False


# ═══════════════════════════════════════════════════════════════════════
# evaluate_alerts integration tests
# ═══════════════════════════════════════════════════════════════════════


class TestEvaluateAlerts:
    """Test AlertService.evaluate_alerts() end-to-end with mocked DB."""

    @pytest.mark.asyncio
    async def test_creates_alert_events(self) -> None:
        """evaluate_alerts should create AlertEvent rows for triggered rules."""
        db = AsyncMock()
        db.add = MagicMock()

        service = AlertService(db)
        service._get_shop_id = AsyncMock(return_value=1)  # type: ignore[method-assign]
        service._get_our_price = AsyncMock(return_value=Decimal("100"))  # type: ignore[method-assign]

        rule = _make_rule(type="price_change", threshold_pct=5.0, channels={})
        service._get_enabled_rules = AsyncMock(return_value=[rule])  # type: ignore[method-assign]

        cp = _make_cp()
        events = await service.evaluate_alerts(
            competitor_product=cp,
            old_price=Decimal("100"),
            new_price=Decimal("80"),  # 20% change
            currency="USD",
            in_stock=True,
            old_in_stock=True,
        )

        assert len(events) == 1
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_events_when_no_rules(self) -> None:
        """No AlertRules → no events."""
        db = AsyncMock()

        service = AlertService(db)
        service._get_shop_id = AsyncMock(return_value=1)  # type: ignore[method-assign]
        service._get_our_price = AsyncMock(return_value=Decimal("100"))  # type: ignore[method-assign]
        service._get_enabled_rules = AsyncMock(return_value=[])  # type: ignore[method-assign]

        cp = _make_cp()
        events = await service.evaluate_alerts(
            competitor_product=cp,
            old_price=Decimal("100"),
            new_price=Decimal("80"),
            currency="USD",
            in_stock=True,
            old_in_stock=True,
        )

        assert len(events) == 0


# ═══════════════════════════════════════════════════════════════════════
# DLQ notification tests
# ═══════════════════════════════════════════════════════════════════════


class TestNotifyScrapingFailures:
    """Test AlertService.notify_scraping_failures()."""

    @pytest.mark.asyncio
    async def test_sends_webhook_on_failure(self) -> None:
        """Should POST to the webhook URL when a CP enters the DLQ."""
        db = AsyncMock()
        service = AlertService(db)

        cp = _make_cp()

        with patch("price_radar.application.alert_service.httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.is_success = True
            mock_post.return_value = mock_resp

            result = await service.notify_scraping_failures(
                competitor_product=cp,
                consecutive_failures=3,
                last_error="captcha_detected",
                webhook_url="https://hooks.example.com/alert",
            )

        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "captcha_detected" in call_kwargs.kwargs.get("json", {}).get("last_error", "")

    @pytest.mark.asyncio
    async def test_returns_false_without_webhook(self) -> None:
        """Should return False when no webhook is configured."""
        db = AsyncMock()
        service = AlertService(db)
        service._get_shop_id = AsyncMock(return_value=1)  # type: ignore[method-assign]
        service._get_shop_webhook = AsyncMock(return_value=None)  # type: ignore[method-assign]

        cp = _make_cp()

        result = await service.notify_scraping_failures(
            competitor_product=cp,
            consecutive_failures=3,
            last_error="captcha_detected",
            webhook_url=None,
        )

        assert result is False
