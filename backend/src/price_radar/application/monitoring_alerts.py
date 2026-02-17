"""Monitoring alerts — fire webhooks when scraping health degrades.

Sends a POST request to a configured webhook URL when:
- A domain's 24h success rate drops below a threshold (default 50%)
- Called from the periodic ``check_scraping_alerts`` Celery task

The webhook payload is a JSON body compatible with Slack incoming
webhooks, Discord webhooks, and generic HTTP receivers::

    {
        "text": "...",           # Slack-compatible
        "content": "...",        # Discord-compatible
        "domains": [...],
        "timestamp": "..."
    }

Usage::

    from price_radar.application.monitoring_alerts import send_alert

    await send_alert(
        webhook_url="https://hooks.slack.com/services/...",
        domains=["amazon.com", "bestbuy.com"],
        threshold=50.0,
    )
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)


def send_alert(
    *,
    webhook_url: str,
    domains: list[str],
    threshold: float,
) -> bool:
    """Fire a webhook alert for domains below the success threshold.

    Args:
        webhook_url: The URL to POST the alert payload to.
        domains: List of domain names that are below threshold.
        threshold: The success rate threshold that was breached.

    Returns:
        ``True`` if the webhook responded 2xx, ``False`` otherwise.
    """
    if not webhook_url or not domains:
        return False

    now = datetime.now(timezone.utc).isoformat()
    domain_list = ", ".join(domains)
    text = (
        f":warning: *Price Radar Alert* — {len(domains)} domain(s) below "
        f"{threshold}% success rate in the last 24h:\n"
        f"`{domain_list}`\n"
        f"Check the dashboard: /internal/scraping/dashboard"
    )

    payload = {
        "text": text,             # Slack
        "content": text,          # Discord
        "domains": domains,
        "threshold": threshold,
        "timestamp": now,
    }

    try:
        resp = httpx.post(
            webhook_url,
            json=payload,
            timeout=10,
            headers={"Content-Type": "application/json"},
        )
        if resp.is_success:
            logger.info(
                "Alert webhook sent successfully for %d domain(s)", len(domains)
            )
            return True
        else:
            logger.warning(
                "Alert webhook returned %d: %s",
                resp.status_code,
                resp.text[:200],
            )
            return False
    except Exception:
        logger.exception("Failed to send alert webhook to %s", webhook_url)
        return False
