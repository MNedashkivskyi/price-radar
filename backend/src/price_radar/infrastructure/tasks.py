"""Celery tasks — product import and competitor price scraping."""

import asyncio
import logging
from typing import Any

from sqlalchemy import select

from price_radar.application.product_import_service import ProductImportService
from price_radar.application.scraping_service import ScrapingService
from price_radar.application.shopify_service import ShopifyService
from price_radar.infrastructure.celery_app import celery_app
from price_radar.infrastructure.database import async_session_maker
from price_radar.infrastructure.models import CompetitorProduct, Shop

logger = logging.getLogger(__name__)


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

    Args:
        self: Celery task instance (for retry support).
        competitor_product_id: Database ID of the CompetitorProduct to scrape.

    Returns:
        Dict with scrape outcome (success, price, method, etc.).
    """
    return asyncio.run(
        _run_scrape_one(competitor_product_id, task=self)
    )


async def _run_scrape_one(
    competitor_product_id: int, task: Any
) -> dict[str, Any]:
    """Async wrapper — opens a DB session and delegates to ScrapingService."""
    async with async_session_maker() as db:
        service = ScrapingService(db)
        result = await service.scrape_one(competitor_product_id)

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
