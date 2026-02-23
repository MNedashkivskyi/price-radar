"""Alert service — evaluates alert rules and fires notifications.

After each successful scrape that produces a price change, the
:meth:`AlertService.evaluate_alerts` method checks all enabled
:class:`AlertRule` rows for the shop and creates :class:`AlertEvent`
rows when conditions are met.

Additionally, :meth:`AlertService.notify_scraping_failures` sends a
webhook when a :class:`CompetitorProduct` reaches the dead-letter
failure threshold so the shop owner is informed.

Usage::

    from price_radar.application.alert_service import AlertService

    service = AlertService(db)
    events = await service.evaluate_alerts(
        competitor_product=cp,
        old_price=Decimal("39.99"),
        new_price=Decimal("29.99"),
        currency="USD",
        in_stock=True,
        old_in_stock=True,
    )
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from price_radar.infrastructure.models import (
    AlertEvent,
    AlertRule,
    Competitor,
    CompetitorProduct,
    Product,
)

logger = logging.getLogger(__name__)


class AlertService:
    """Evaluate alert rules and dispatch notifications."""

    def __init__(self, db: "AsyncSession") -> None:
        self._db = db

    # ── Public API ───────────────────────────────────────────────────

    async def evaluate_alerts(
        self,
        *,
        competitor_product: CompetitorProduct,
        old_price: Decimal | None,
        new_price: Decimal,
        currency: str,
        in_stock: bool,
        old_in_stock: bool | None,
    ) -> list[AlertEvent]:
        """Evaluate all enabled alert rules after a price change.

        Args:
            competitor_product: The CP that was just scraped.
            old_price: Previous price (``None`` on first scrape).
            new_price: Newly extracted price.
            currency: ISO 4217 currency code.
            in_stock: Current stock status.
            old_in_stock: Previous stock status (``None`` on first scrape).

        Returns:
            List of newly created :class:`AlertEvent` rows (already
            added to the session but **not** committed).
        """
        shop_id = await self._get_shop_id(competitor_product.competitor_id)
        if shop_id is None:
            return []

        our_price = await self._get_our_price(competitor_product.product_id)
        rules = await self._get_enabled_rules(shop_id)
        if not rules:
            return []

        now = datetime.now(timezone.utc)
        events: list[AlertEvent] = []

        for rule in rules:
            triggered = self._check_rule(
                rule,
                old_price=old_price,
                new_price=new_price,
                our_price=our_price,
                in_stock=in_stock,
                old_in_stock=old_in_stock,
            )
            if not triggered:
                continue

            event = AlertEvent(
                alert_rule_id=rule.id,
                competitor_product_id=competitor_product.id,
                old_price=float(old_price) if old_price is not None else None,
                new_price=float(new_price),
                triggered_at=now,
            )
            self._db.add(event)
            events.append(event)

            # Deliver via configured channels
            await self._deliver_alert(rule, event, competitor_product)

        if events:
            logger.info(
                "Triggered %d alert(s) for cp=%d (price %s → %s)",
                len(events),
                competitor_product.id,
                old_price,
                new_price,
            )

        return events

    async def notify_scraping_failures(
        self,
        *,
        competitor_product: CompetitorProduct,
        consecutive_failures: int,
        last_error: str,
        webhook_url: str | None = None,
    ) -> bool:
        """Send a notification when a CP enters the dead-letter queue.

        Called when ``consecutive_failures`` reaches the threshold and
        the CP status is set to ``"failed"``.

        Args:
            competitor_product: The failed CP.
            consecutive_failures: Current failure count.
            last_error: Most recent error string.
            webhook_url: Monitoring webhook URL.  Falls back to the
                shop's alert rule webhook if available.

        Returns:
            ``True`` if a notification was sent successfully.
        """
        target_url = webhook_url
        if not target_url:
            shop_id = await self._get_shop_id(competitor_product.competitor_id)
            if shop_id:
                target_url = await self._get_shop_webhook(shop_id)

        if not target_url:
            logger.info(
                "No webhook configured for DLQ notification: cp=%d",
                competitor_product.id,
            )
            return False

        now = datetime.now(timezone.utc).isoformat()
        text = (
            f":x: *Price Radar — Scraping Failed*\n"
            f"URL `{competitor_product.url}` has failed "
            f"{consecutive_failures} consecutive times and has been "
            f"moved to the dead-letter queue.\n"
            f"Last error: `{last_error}`\n"
            f"Action required: check the URL or remove it from tracking."
        )

        payload = {
            "text": text,
            "content": text,
            "competitor_product_id": competitor_product.id,
            "url": competitor_product.url,
            "consecutive_failures": consecutive_failures,
            "last_error": last_error,
            "timestamp": now,
        }

        try:
            resp = httpx.post(
                target_url,
                json=payload,
                timeout=10,
                headers={"Content-Type": "application/json"},
            )
            if resp.is_success:
                logger.info(
                    "DLQ notification sent for cp=%d url=%s",
                    competitor_product.id,
                    competitor_product.url,
                )
                return True
            logger.warning(
                "DLQ webhook returned %d for cp=%d",
                resp.status_code,
                competitor_product.id,
            )
            return False
        except Exception:
            logger.exception(
                "Failed to send DLQ notification for cp=%d",
                competitor_product.id,
            )
            return False

    # ── Rule evaluation ──────────────────────────────────────────────

    @staticmethod
    def _check_rule(
        rule: AlertRule,
        *,
        old_price: Decimal | None,
        new_price: Decimal,
        our_price: Decimal | None,
        in_stock: bool,
        old_in_stock: bool | None,
    ) -> bool:
        """Return ``True`` if the alert rule conditions are met."""
        threshold_pct = float(rule.threshold_pct or 0)

        if rule.type == "undercut":
            # Competitor's price dropped below our price by threshold %
            if our_price is None:
                return False
            threshold_price = float(our_price) * (1 - threshold_pct / 100)
            return float(new_price) < threshold_price

        if rule.type == "price_change":
            # Price changed by more than threshold %
            if old_price is None or float(old_price) == 0:
                return False
            change_pct = abs(float(new_price) - float(old_price)) / float(old_price) * 100
            return change_pct >= threshold_pct

        if rule.type == "stock_change":
            # Stock status changed
            if old_in_stock is None:
                return False
            return in_stock != old_in_stock

        return False

    # ── Notification delivery ────────────────────────────────────────

    async def _deliver_alert(
        self,
        rule: AlertRule,
        event: AlertEvent,
        cp: CompetitorProduct,
    ) -> None:
        """Deliver an alert via the channels configured on the rule."""
        channels = rule.channels or {}

        webhook_url = channels.get("webhook")
        if webhook_url and isinstance(webhook_url, str):
            self._send_webhook(webhook_url, rule, event, cp)

        # Email and Slack channels are logged but not yet implemented
        if channels.get("email"):
            logger.info(
                "Email alert would be sent for rule=%d event=%d (not yet implemented)",
                rule.id,
                event.id if event.id else 0,
            )

    @staticmethod
    def _send_webhook(
        url: str,
        rule: AlertRule,
        event: AlertEvent,
        cp: CompetitorProduct,
    ) -> None:
        """POST an alert payload to a webhook URL."""
        now = datetime.now(timezone.utc).isoformat()
        text = (
            f":bell: *Price Radar Alert* — {rule.type}\n"
            f"URL: `{cp.url}`\n"
            f"Price: {event.old_price} → {event.new_price}\n"
        )
        payload = {
            "text": text,
            "content": text,
            "alert_type": rule.type,
            "competitor_product_id": cp.id,
            "url": cp.url,
            "old_price": event.old_price,
            "new_price": float(event.new_price),
            "timestamp": now,
        }
        try:
            resp = httpx.post(
                url, json=payload, timeout=10,
                headers={"Content-Type": "application/json"},
            )
            if not resp.is_success:
                logger.warning(
                    "Alert webhook returned %d for rule=%d",
                    resp.status_code, rule.id,
                )
        except Exception:
            logger.exception("Failed to send alert webhook for rule=%d", rule.id)

    # ── DB queries ───────────────────────────────────────────────────

    async def _get_shop_id(self, competitor_id: int) -> int | None:
        """Resolve shop_id from a competitor_id."""
        result = await self._db.execute(
            select(Competitor.shop_id).where(Competitor.id == competitor_id)
        )
        return result.scalar_one_or_none()

    async def _get_our_price(self, product_id: int) -> Decimal | None:
        """Get the merchant's own price for a product."""
        result = await self._db.execute(
            select(Product.our_price).where(Product.id == product_id)
        )
        val = result.scalar_one_or_none()
        return Decimal(str(val)) if val is not None else None

    async def _get_enabled_rules(self, shop_id: int) -> list[AlertRule]:
        """Load all enabled alert rules for a shop."""
        result = await self._db.execute(
            select(AlertRule).where(
                AlertRule.shop_id == shop_id,
                AlertRule.enabled == True,  # noqa: E712
            )
        )
        return list(result.scalars().all())

    async def _get_shop_webhook(self, shop_id: int) -> str | None:
        """Find the first webhook URL from the shop's alert rules."""
        rules = await self._get_enabled_rules(shop_id)
        for rule in rules:
            channels = rule.channels or {}
            url = channels.get("webhook")
            if url and isinstance(url, str):
                return url
        return None
