"""Celery tasks — product import and competitor price scraping."""

import asyncio
import logging
from typing import Any

from sqlalchemy import select

from price_radar.application.product_import_service import ProductImportService
from price_radar.application.rate_limiter import RateLimitExceeded
from price_radar.application.scraping_service import ScrapingService
from price_radar.application.shopify_service import ShopifyService
from price_radar.infrastructure.celery_app import celery_app
from price_radar.infrastructure.database import async_session_maker
from price_radar.infrastructure.models import CompetitorProduct, Shop

logger = logging.getLogger(__name__)

# Maximum seconds the scrape task will wait for a rate limit slot.
# If exceeded, the task re-queues itself with a countdown instead of
# blocking the Celery worker.
_RATE_LIMIT_MAX_WAIT = 60.0
_RATE_LIMIT_REQUEUE_COUNTDOWN = 30  # seconds before the re-queued task runs


# ═══════════════════════════════════════════════════════════════════════
# Example / Health-check
# ═══════════════════════════════════════════════════════════════════════

@celery_app.task  # type: ignore[untyped-decorator]
def example_task() -> str:
    """Example Celery task."""
    return "Task completed"


# ═══════════════════════════════════════════════════════════════════════
# Product import
# ═══════════════════════════════════════════════════════════════════════

@celery_app.task(bind=True)  # type: ignore[untyped-decorator]
def import_products_task(self: Any, shop_id: int) -> dict[str, Any]:
    """Background task to import products from Shopify.

    This task runs asynchronously for shops with large product catalogs.

    Args:
        self: Celery task instance (for progress updates)
        shop_id: Shop database ID

    Returns:
        Import statistics
    """
    # Update task state to STARTED
    self.update_state(state="STARTED", meta={"shop_id": shop_id, "progress": 0})

    # Run async import in sync context
    result = asyncio.run(_run_product_import(shop_id, self))

    return result


async def _run_product_import(shop_id: int, task: Any) -> dict[str, Any]:
    """Run product import asynchronously.

    Args:
        shop_id: Shop database ID
        task: Celery task instance for progress updates

    Returns:
        Import statistics
    """
    async with async_session_maker() as db:
        # Get shop with access token
        result = await db.execute(select(Shop).where(Shop.id == shop_id))
        shop = result.scalar_one_or_none()

        if not shop:
            return {"error": "Shop not found", "shop_id": shop_id}

        # Decrypt access token
        shopify_service = ShopifyService(db)
        decrypted_token = shopify_service.decrypt_token(shop.access_token)

        # Update progress
        task.update_state(
            state="PROGRESS",
            meta={"shop_id": shop_id, "progress": 10, "status": "Starting import..."},
        )

        # Run import
        import_service = ProductImportService(db)

        try:
            stats = await import_service.import_products(
                shop_id=shop.id, access_token=decrypted_token, shop_domain=shop.shopify_domain
            )

            task.update_state(
                state="PROGRESS",
                meta={
                    "shop_id": shop_id,
                    "progress": 100,
                    "status": "Import complete",
                    "stats": stats,
                },
            )

            return stats

        except Exception as e:
            task.update_state(
                state="FAILURE",
                meta={"shop_id": shop_id, "error": str(e), "status": "Import failed"},
            )
            raise


# ═══════════════════════════════════════════════════════════════════════
# Price scraping
# ═══════════════════════════════════════════════════════════════════════

@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=900,
    retry_jitter=True,
    max_retries=3,
)
def scrape_competitor_product(
    self: Any, competitor_product_id: int
) -> dict[str, Any]:
    """Scrape a single competitor product URL and store the price.

    This is the core scraping task.  It is typically dispatched by
    :func:`scrape_all_active` (the fan-out task) but can also be called
    directly via ``scrape_competitor_product.delay(cp_id)``.

    The task uses Celery auto-retry with exponential backoff (60s base,
    max 15min, up to 3 retries) for transient failures.

    **Rate limiting:** If the per-domain rate limit would require waiting
    longer than ``_RATE_LIMIT_MAX_WAIT`` seconds, the task re-queues
    itself with a countdown instead of blocking the worker.

    Args:
        self: Celery task instance (for retry support).
        competitor_product_id: Database ID of the CompetitorProduct to scrape.

    Returns:
        Dict with scrape outcome (success, price, method, etc.).
    """
    try:
        return asyncio.run(
            _run_scrape_one(competitor_product_id, task=self)
        )
    except RateLimitExceeded as exc:
        logger.info(
            "Rate limit exceeded for cp=%d (%s), re-queuing in %ds",
            competitor_product_id,
            exc.domain,
            _RATE_LIMIT_REQUEUE_COUNTDOWN,
        )
        # Re-queue with countdown — does NOT count as a retry
        self.apply_async(
            args=[competitor_product_id],
            countdown=_RATE_LIMIT_REQUEUE_COUNTDOWN,
        )
        return {
            "competitor_product_id": competitor_product_id,
            "success": False,
            "error": f"rate_limited:{exc.domain}",
            "requeued": True,
            "requeue_countdown": _RATE_LIMIT_REQUEUE_COUNTDOWN,
        }


def _get_redis_client():  # type: ignore[no-untyped-def]
    """Create a Redis client from application settings (lazy import)."""
    from price_radar.infrastructure.config import settings
    import redis as redis_lib

    return redis_lib.Redis.from_url(settings.redis_url, decode_responses=True)


async def _run_scrape_one(
    competitor_product_id: int, task: Any
) -> dict[str, Any]:
    """Async wrapper — opens a DB session and delegates to ScrapingService.

    Creates a ``DomainRateLimiter`` and ``DomainCircuitBreaker`` backed by
    the application Redis and injects them into the ``PageFetcher`` used
    by ``ScrapingService``.  The ``RateLimitExceeded`` exception is NOT
    caught here — it propagates to the Celery task for re-queue handling.
    """
    from price_radar.application.circuit_breaker import DomainCircuitBreaker
    from price_radar.application.price_extraction.fetcher import PageFetcher
    from price_radar.application.rate_limiter import DomainRateLimiter

    redis_client = _get_redis_client()
    rate_limiter = DomainRateLimiter(redis_client)
    circuit_breaker = DomainCircuitBreaker(redis_client)
    fetcher = PageFetcher(
        use_playwright=True,
        rate_limiter=rate_limiter,
        circuit_breaker=circuit_breaker,
        rate_limit_max_wait=_RATE_LIMIT_MAX_WAIT,
    )

    async with async_session_maker() as db:
        service = ScrapingService(db, fetcher=fetcher)
        result = await service.scrape_one(competitor_product_id)

    # ── Record scraping metrics ──────────────────────────────────────
    try:
        from price_radar.application.rate_limiter import extract_domain
        from price_radar.application.scraping_metrics import ScrapingMetrics

        # Determine domain from the competitor product URL (available in
        # the result's fetch_method, but we need the URL).  The easiest
        # approach: read the URL from the DB result via a lightweight
        # query, OR infer the domain from the task context.  Since the
        # result already contains fetch_method and error, we can infer
        # the domain from the competitor product in the DB session above.
        # For simplicity, open a short session to grab the URL.
        async with async_session_maker() as db2:
            from sqlalchemy import select as _select

            row = await db2.execute(
                _select(CompetitorProduct.url).where(
                    CompetitorProduct.id == competitor_product_id
                )
            )
            url = row.scalar_one_or_none()

        if url:
            domain = extract_domain(url)
            metrics = ScrapingMetrics(redis_client)
            metrics.record_scrape(
                domain,
                success=result.success,
                fetch_method=result.fetch_method,
                fetch_time=result.fetch_time,
                error=result.error if not result.success else None,
            )
    except Exception:
        logger.debug("Failed to record scraping metrics", exc_info=True)

    return {
        "competitor_product_id": result.competitor_product_id,
        "success": result.success,
        "price": float(result.price) if result.price else None,
        "currency": result.currency,
        "in_stock": result.in_stock,
        "fetch_method": result.fetch_method,
        "was_deduplicated": result.was_deduplicated,
        "error": result.error,
        "fetch_time": round(result.fetch_time, 2),
        "confidence": round(result.confidence, 2),
        "strategies_used": result.strategies_used,
    }


@celery_app.task  # type: ignore[untyped-decorator]
def scrape_all_active(plan: str | None = None) -> dict[str, Any]:
    """Fan-out task: dispatch scrape tasks for all active CompetitorProducts.

    Called periodically by Celery Beat.  Queries the DB for all
    ``CompetitorProduct`` rows with ``status='active'`` (optionally filtered
    by shop plan) and dispatches a :func:`scrape_competitor_product` task
    for each.

    Args:
        plan: Optional shop plan filter (``"free"``, ``"pro"``, etc.).
            When ``None``, scrapes ALL active competitor products.

    Returns:
        Dict with the number of tasks dispatched.
    """
    return asyncio.run(_run_scrape_all_active(plan))


async def _run_scrape_all_active(plan: str | None) -> dict[str, Any]:
    """Query active CompetitorProducts and fan out individual tasks."""
    async with async_session_maker() as db:
        query = select(CompetitorProduct.id).where(
            CompetitorProduct.status.in_(["active"])
        )

        if plan is not None:
            # Join through Competitor → Shop to filter by plan
            from price_radar.infrastructure.models import Competitor

            query = (
                query.join(
                    Competitor,
                    CompetitorProduct.competitor_id == Competitor.id,
                )
                .join(Shop, Competitor.shop_id == Shop.id)
                .where(Shop.plan == plan)
            )

        result = await db.execute(query)
        cp_ids = [row[0] for row in result.all()]

    # Dispatch individual scrape tasks
    dispatched = 0
    for cp_id in cp_ids:
        scrape_competitor_product.delay(cp_id)
        dispatched += 1

    logger.info(
        "scrape_all_active: dispatched %d tasks (plan=%s)",
        dispatched,
        plan or "all",
    )

    return {
        "dispatched": dispatched,
        "plan_filter": plan,
    }


# ═══════════════════════════════════════════════════════════════════════
# Circuit breaker probe
# ═══════════════════════════════════════════════════════════════════════

@celery_app.task  # type: ignore[untyped-decorator]
def probe_broken_domains() -> dict[str, Any]:
    """Probe domains with OPEN circuit breakers to check if they recovered.

    Runs hourly via Celery Beat.  For each OPEN domain whose recovery
    timeout has expired, the circuit breaker transitions to HALF_OPEN and
    ``allow_request`` will permit exactly one probe.  We find one active
    CompetitorProduct URL for that domain and dispatch a normal
    ``scrape_competitor_product`` task.  The fetch pipeline's circuit
    breaker integration will automatically record success/failure,
    transitioning the circuit to CLOSED or back to OPEN.

    Returns:
        Dict with probe results.
    """
    return asyncio.run(_run_probe_broken_domains())


async def _run_probe_broken_domains() -> dict[str, Any]:
    """Query OPEN domains and dispatch one probe task per domain."""
    from price_radar.application.circuit_breaker import DomainCircuitBreaker
    from price_radar.application.rate_limiter import extract_domain

    redis_client = _get_redis_client()
    cb = DomainCircuitBreaker(redis_client)

    open_domains = cb.get_open_domains()
    if not open_domains:
        return {"probed": 0, "domains": []}

    probed_domains: list[str] = []

    async with async_session_maker() as db:
        for domain in open_domains:
            # Check if recovery timeout has expired (allow_request transitions
            # OPEN → HALF_OPEN if next_retry_at has passed)
            if not cb.allow_request(domain):
                continue  # Still in OPEN cooldown

            # Find one active CompetitorProduct URL for this domain
            result = await db.execute(
                select(CompetitorProduct.id, CompetitorProduct.url)
                .where(CompetitorProduct.status.in_(["active", "failed"]))
            )
            rows = result.all()

            # Filter by domain
            probe_cp_id = None
            for cp_id, url in rows:
                if extract_domain(url) == domain:
                    probe_cp_id = cp_id
                    break

            if probe_cp_id is not None:
                scrape_competitor_product.delay(probe_cp_id)
                probed_domains.append(domain)
                logger.info(
                    "Circuit probe: dispatched scrape for cp=%d on domain %s",
                    probe_cp_id,
                    domain,
                )

    return {
        "probed": len(probed_domains),
        "domains": probed_domains,
    }


# ═══════════════════════════════════════════════════════════════════════
# Monitoring alerts
# ═══════════════════════════════════════════════════════════════════════

@celery_app.task  # type: ignore[untyped-decorator]
def check_scraping_alerts() -> dict[str, Any]:
    """Check scraping health and fire webhook alerts if degraded.

    Runs every 30 minutes via Celery Beat.  Reads 24h metrics and sends
    a webhook alert for any domains whose success rate is below the
    configured threshold.

    Returns:
        Dict with alert results.
    """
    from price_radar.application.monitoring_alerts import send_alert
    from price_radar.application.scraping_metrics import ScrapingMetrics
    from price_radar.infrastructure.config import settings as _settings

    webhook_url = _settings.monitoring_alert_webhook_url
    threshold = _settings.monitoring_alert_threshold

    if not webhook_url:
        return {"alerted": False, "reason": "no_webhook_url_configured"}

    redis_client = _get_redis_client()
    metrics = ScrapingMetrics(redis_client)
    health = metrics.get_health_summary(alert_threshold=threshold)

    if not health.domains_below_threshold:
        return {"alerted": False, "reason": "all_domains_healthy"}

    success = send_alert(
        webhook_url=webhook_url,
        domains=health.domains_below_threshold,
        threshold=threshold,
    )

    return {
        "alerted": success,
        "domains": health.domains_below_threshold,
        "threshold": threshold,
    }
