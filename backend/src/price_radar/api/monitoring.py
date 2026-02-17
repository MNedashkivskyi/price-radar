"""Internal monitoring API — scraping health, domain stats, failures.

All endpoints live under ``/internal/scraping/`` and are protected by an
optional API key (configured via ``MONITORING_API_KEY`` env var).

Endpoints:
    GET /internal/scraping/health     — overall success rate, queue depth
    GET /internal/scraping/domains    — per-domain stats (24h)
    GET /internal/scraping/failures   — recent failures by error type
    GET /internal/scraping/dashboard  — HTML dashboard (Jinja2)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from price_radar.infrastructure.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/scraping", tags=["monitoring"])

# ── Auth dependency ──────────────────────────────────────────────────────


def _verify_api_key(request: Request) -> None:
    """Check ``X-API-Key`` header against configured monitoring key.

    If ``MONITORING_API_KEY`` is empty/unset, authentication is disabled
    (all requests are allowed).  This lets local dev work without config.
    """
    api_key = settings.monitoring_api_key
    if not api_key:
        return  # Auth disabled

    provided = request.headers.get("X-API-Key", "")
    if provided != api_key:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")


# ── Helpers ──────────────────────────────────────────────────────────────


def _get_redis():  # type: ignore[no-untyped-def]
    """Lazy-import Redis client from app settings."""
    try:
        import redis as redis_lib

        return redis_lib.Redis.from_url(settings.redis_url, decode_responses=True)
    except Exception:
        return None


def _get_queue_depth(redis_client: object | None) -> int:
    """Read the Celery default queue length from the broker Redis."""
    if redis_client is None:
        return 0
    try:
        import redis as redis_lib

        broker = redis_lib.Redis.from_url(
            settings.celery_broker_url, decode_responses=True
        )
        depth = broker.llen("celery")  # default queue name
        return int(depth) if depth else 0
    except Exception:
        return 0


def _format_timestamp(ts: float | None) -> str | None:
    """Convert a Unix timestamp to an ISO-8601 string (or None)."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# ── Endpoints ────────────────────────────────────────────────────────────


@router.get("/health", dependencies=[Depends(_verify_api_key)])
def scraping_health() -> dict[str, Any]:
    """Overall scraping health — success rate, queue depth, active domains."""
    from price_radar.application.scraping_metrics import ScrapingMetrics

    redis_client = _get_redis()
    metrics = ScrapingMetrics(redis_client)

    queue_depth = _get_queue_depth(redis_client)
    health = metrics.get_health_summary(
        alert_threshold=settings.monitoring_alert_threshold,
        queue_depth=queue_depth,
    )

    if health.total_scrapes_24h == 0:
        status = "idle"
    elif health.success_rate_24h >= 50.0:
        status = "healthy"
    else:
        status = "degraded"

    return {
        "status": status,
        "total_scrapes_24h": health.total_scrapes_24h,
        "success_24h": health.success_24h,
        "failure_24h": health.failure_24h,
        "success_rate_24h": health.success_rate_24h,
        "active_domains": health.active_domains,
        "domains_below_threshold": health.domains_below_threshold,
        "queue_depth": health.queue_depth,
        "timestamp": _format_timestamp(health.timestamp),
    }


@router.get("/domains", dependencies=[Depends(_verify_api_key)])
def scraping_domains(days: int = 1) -> list[dict[str, Any]]:
    """Per-domain stats — success rate, avg fetch time, method distribution,
    circuit breaker state, last success timestamp.

    Query params:
        days: Number of days to aggregate (default 1).
    """
    from price_radar.application.circuit_breaker import DomainCircuitBreaker
    from price_radar.application.scraping_metrics import ScrapingMetrics

    redis_client = _get_redis()
    metrics = ScrapingMetrics(redis_client)
    cb = DomainCircuitBreaker(redis_client)

    domains = metrics.get_tracked_domains()
    result: list[dict[str, Any]] = []

    for domain in domains:
        stats = metrics.get_domain_stats(domain, days=days)
        circuit = cb.get_status(domain)

        result.append({
            "domain": domain,
            "total": stats.total,
            "success": stats.success,
            "failure": stats.failure,
            "success_rate": round(stats.success_rate, 2),
            "avg_fetch_time": round(stats.avg_fetch_time, 3),
            "method_distribution": {
                "httpx": stats.method_httpx,
                "camoufox": stats.method_camoufox,
                "none": stats.method_none,
            },
            "circuit_breaker": {
                "state": circuit.state.value,
                "failure_count": circuit.failure_count,
                "next_retry_at": _format_timestamp(circuit.next_retry_at),
            },
            "last_success_at": _format_timestamp(stats.last_success_at),
            "errors": stats.errors,
        })

    # Sort by total scrapes descending
    result.sort(key=lambda d: d["total"], reverse=True)
    return result


@router.get("/failures", dependencies=[Depends(_verify_api_key)])
def scraping_failures(days: int = 1) -> list[dict[str, Any]]:
    """Recent failures grouped by error type and domain.

    Query params:
        days: Number of days to look back (default 1).
    """
    from price_radar.application.scraping_metrics import ScrapingMetrics

    redis_client = _get_redis()
    metrics = ScrapingMetrics(redis_client)
    groups = metrics.get_failure_groups(days=days)

    return [
        {
            "error_type": g.error_type,
            "domain": g.domain,
            "count": g.count,
            "last_seen": g.last_seen,
        }
        for g in groups
    ]


@router.get("/dashboard", dependencies=[Depends(_verify_api_key)],
            response_class=HTMLResponse)
def scraping_dashboard() -> HTMLResponse:
    """Simple HTML dashboard rendering all monitoring data.

    Auto-refreshes every 60 seconds.  Designed for quick visual checks —
    not a replacement for a full monitoring stack.
    """
    from price_radar.application.circuit_breaker import DomainCircuitBreaker
    from price_radar.application.scraping_metrics import ScrapingMetrics

    redis_client = _get_redis()
    metrics = ScrapingMetrics(redis_client)
    cb = DomainCircuitBreaker(redis_client)

    queue_depth = _get_queue_depth(redis_client)
    health = metrics.get_health_summary(
        alert_threshold=settings.monitoring_alert_threshold,
        queue_depth=queue_depth,
    )

    # Per-domain data
    domains = metrics.get_tracked_domains()
    domain_rows: list[dict[str, Any]] = []
    for domain in domains:
        stats = metrics.get_domain_stats(domain, days=1)
        circuit = cb.get_status(domain)
        domain_rows.append({
            "domain": domain,
            "total": stats.total,
            "success": stats.success,
            "failure": stats.failure,
            "success_rate": round(stats.success_rate, 1),
            "avg_fetch_time": round(stats.avg_fetch_time, 2),
            "method_httpx": stats.method_httpx,
            "method_camoufox": stats.method_camoufox,
            "circuit_state": circuit.state.value,
            "circuit_failures": circuit.failure_count,
            "last_success": _format_timestamp(stats.last_success_at) or "—",
            "errors": stats.errors,
        })
    domain_rows.sort(key=lambda d: d["total"], reverse=True)

    # Failures
    failure_groups = metrics.get_failure_groups(days=1)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    html = _render_dashboard(health, domain_rows, failure_groups, now_str)
    return HTMLResponse(content=html)


# ── HTML template ────────────────────────────────────────────────────────


def _render_dashboard(
    health: Any,
    domain_rows: list[dict[str, Any]],
    failure_groups: list[Any],
    now_str: str,
) -> str:
    """Render the monitoring dashboard HTML."""

    # Health status color
    if health.total_scrapes_24h == 0:
        status_color = "#64748b"
        status_text = "Idle"
    elif health.success_rate_24h >= 90:
        status_color = "#22c55e"
        status_text = "Healthy"
    elif health.success_rate_24h >= 50:
        status_color = "#f59e0b"
        status_text = "Degraded"
    else:
        status_color = "#ef4444"
        status_text = "Critical"

    # Domain table rows
    domain_html = ""
    for d in domain_rows:
        # Color-code success rate
        rate = d["success_rate"]
        if rate >= 90:
            rate_class = "good"
        elif rate >= 50:
            rate_class = "warn"
        else:
            rate_class = "bad"

        # Circuit breaker badge
        cb_state = d["circuit_state"]
        if cb_state == "closed":
            cb_badge = '<span class="badge badge-green">CLOSED</span>'
        elif cb_state == "half_open":
            cb_badge = '<span class="badge badge-yellow">HALF_OPEN</span>'
        else:
            cb_badge = '<span class="badge badge-red">OPEN</span>'

        # Error summary
        err_parts = [f"{k}: {v}" for k, v in d["errors"].items()]
        err_str = ", ".join(err_parts) if err_parts else "—"

        domain_html += f"""
        <tr>
            <td><strong>{d['domain']}</strong></td>
            <td>{d['total']}</td>
            <td>{d['success']}</td>
            <td>{d['failure']}</td>
            <td class="{rate_class}">{rate}%</td>
            <td>{d['avg_fetch_time']}s</td>
            <td>{d['method_httpx']} / {d['method_camoufox']}</td>
            <td>{cb_badge}</td>
            <td class="small">{d['last_success']}</td>
            <td class="small">{err_str}</td>
        </tr>"""

    # Failure table rows
    failure_html = ""
    for f in failure_groups[:20]:  # Top 20
        failure_html += f"""
        <tr>
            <td><code>{f.error_type}</code></td>
            <td>{f.domain}</td>
            <td>{f.count}</td>
            <td>{f.last_seen}</td>
        </tr>"""

    if not failure_html:
        failure_html = '<tr><td colspan="4" class="empty">No failures in the last 24 hours</td></tr>'

    if not domain_html:
        domain_html = '<tr><td colspan="10" class="empty">No scraping data yet</td></tr>'

    # Alerts section
    alert_html = ""
    if health.domains_below_threshold:
        alert_items = "".join(
            f"<li>{d}</li>" for d in health.domains_below_threshold
        )
        alert_html = f"""
        <div class="alert-box">
            <h3>Domains below {int(health.success_rate_24h)}% success threshold</h3>
            <ul>{alert_items}</ul>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>Price Radar — Scraping Dashboard</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    margin: 0; padding: 20px;
    background: #0f172a; color: #e2e8f0;
  }}
  h1 {{ margin: 0 0 4px; font-size: 1.5rem; }}
  h2 {{ margin: 24px 0 12px; font-size: 1.15rem; color: #94a3b8; }}
  .subtitle {{ color: #64748b; font-size: 0.85rem; margin-bottom: 20px; }}
  .cards {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px; margin-bottom: 20px;
  }}
  .card {{
    background: #1e293b; border-radius: 8px; padding: 16px;
    border: 1px solid #334155;
  }}
  .card .label {{ font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }}
  .card .value {{ font-size: 1.75rem; font-weight: 700; margin-top: 4px; }}
  .card .value.good {{ color: #22c55e; }}
  .card .value.warn {{ color: #f59e0b; }}
  .card .value.bad {{ color: #ef4444; }}
  table {{
    width: 100%; border-collapse: collapse;
    background: #1e293b; border-radius: 8px; overflow: hidden;
  }}
  th {{
    background: #334155; padding: 10px 12px; text-align: left;
    font-size: 0.75rem; text-transform: uppercase; color: #94a3b8;
    letter-spacing: 0.05em;
  }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #334155; font-size: 0.875rem; }}
  tr:last-child td {{ border-bottom: none; }}
  .good {{ color: #22c55e; font-weight: 600; }}
  .warn {{ color: #f59e0b; font-weight: 600; }}
  .bad {{ color: #ef4444; font-weight: 600; }}
  .small {{ font-size: 0.75rem; color: #94a3b8; }}
  .empty {{ text-align: center; color: #64748b; padding: 24px; }}
  .badge {{
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
  }}
  .badge-green {{ background: #166534; color: #86efac; }}
  .badge-yellow {{ background: #854d0e; color: #fde047; }}
  .badge-red {{ background: #991b1b; color: #fca5a5; }}
  .alert-box {{
    background: #451a03; border: 1px solid #92400e; border-radius: 8px;
    padding: 16px; margin-bottom: 20px;
  }}
  .alert-box h3 {{ margin: 0 0 8px; color: #fbbf24; font-size: 0.9rem; }}
  .alert-box ul {{ margin: 0; padding-left: 20px; }}
  .alert-box li {{ color: #fcd34d; font-size: 0.85rem; }}
  code {{ background: #334155; padding: 2px 6px; border-radius: 3px; font-size: 0.8rem; }}
  .status-dot {{
    display: inline-block; width: 10px; height: 10px; border-radius: 50%;
    margin-right: 6px; vertical-align: middle;
  }}
</style>
</head>
<body>

<h1>
  <span class="status-dot" style="background:{status_color}"></span>
  Price Radar — Scraping Dashboard
</h1>
<div class="subtitle">Last updated: {now_str} &middot; Auto-refresh every 60s</div>

{alert_html}

<div class="cards">
  <div class="card">
    <div class="label">Status</div>
    <div class="value" style="color:{status_color}">{status_text}</div>
  </div>
  <div class="card">
    <div class="label">Total Scrapes (24h)</div>
    <div class="value">{health.total_scrapes_24h:,}</div>
  </div>
  <div class="card">
    <div class="label">Success Rate (24h)</div>
    <div class="value {'good' if health.success_rate_24h >= 90 else 'warn' if health.success_rate_24h >= 50 else 'bad'}">{health.success_rate_24h}%</div>
  </div>
  <div class="card">
    <div class="label">Successes</div>
    <div class="value good">{health.success_24h:,}</div>
  </div>
  <div class="card">
    <div class="label">Failures</div>
    <div class="value {'bad' if health.failure_24h > 0 else 'good'}">{health.failure_24h:,}</div>
  </div>
  <div class="card">
    <div class="label">Active Domains</div>
    <div class="value">{health.active_domains}</div>
  </div>
  <div class="card">
    <div class="label">Queue Depth</div>
    <div class="value">{health.queue_depth:,}</div>
  </div>
</div>

<h2>Per-Domain Stats (24h)</h2>
<table>
  <thead>
    <tr>
      <th>Domain</th>
      <th>Total</th>
      <th>OK</th>
      <th>Fail</th>
      <th>Rate</th>
      <th>Avg Time</th>
      <th>httpx / CF</th>
      <th>Circuit</th>
      <th>Last Success</th>
      <th>Errors</th>
    </tr>
  </thead>
  <tbody>
    {domain_html}
  </tbody>
</table>

<h2>Recent Failures (24h)</h2>
<table>
  <thead>
    <tr>
      <th>Error Type</th>
      <th>Domain</th>
      <th>Count</th>
      <th>Last Seen</th>
    </tr>
  </thead>
  <tbody>
    {failure_html}
  </tbody>
</table>

</body>
</html>"""
