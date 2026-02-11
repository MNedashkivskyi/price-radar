"""Celery tasks."""

import asyncio
from typing import Any

from sqlalchemy import select

from backend.src.price_radar.application.product_import_service import ProductImportService
from backend.src.price_radar.application.shopify_service import ShopifyService
from backend.src.price_radar.infrastructure.celery_app import celery_app
from backend.src.price_radar.infrastructure.database import async_session_maker
from backend.src.price_radar.infrastructure.models import Shop


@celery_app.task  # type: ignore[untyped-decorator]
def example_task() -> str:
    """Example Celery task."""
    return "Task completed"


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
