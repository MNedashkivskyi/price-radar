"""Product API endpoints."""

from typing import Any

from celery.result import AsyncResult  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from price_radar.api.middleware import get_current_shop_id
from price_radar.application.product_import_service import ProductImportService
from price_radar.application.shopify_service import ShopifyService
from price_radar.infrastructure.database import get_db
from price_radar.infrastructure.models import Product, Shop
from price_radar.infrastructure.tasks import import_products_task

router = APIRouter(prefix="/products", tags=["products"])


@router.post("/import")
async def import_products(
    shop_id: int = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Import products from Shopify.

    Triggers a background job for large catalogs (>100 products).
    For small catalogs, imports immediately.

    Args:
        shop_id: Authenticated shop ID from JWT
        db: Database session

    Returns:
        Import status and job ID if background task
    """
    # Get shop
    result = await db.execute(select(Shop).where(Shop.id == shop_id))
    shop = result.scalar_one_or_none()

    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    # Get product count to decide sync vs async
    shopify_service = ShopifyService(db)
    decrypted_token = shopify_service.decrypt_token(shop.access_token)

    from price_radar.application.shopify_client import ShopifyAPIClient

    client = ShopifyAPIClient(shop.shopify_domain, decrypted_token)

    try:
        product_count = await client.get_product_count()
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to connect to Shopify: {str(e)}"
        ) from e

    # For large catalogs, use background task
    if product_count > 100:
        # Trigger async Celery task
        task = import_products_task.delay(shop_id)

        return {
            "status": "started",
            "job_id": task.id,
            "product_count": product_count,
            "message": "Import started in background. Use job_id to check progress.",
        }

    # For small catalogs, import immediately
    import_service = ProductImportService(db)
    stats = await import_service.import_products(
        shop_id=shop.id, access_token=decrypted_token, shop_domain=shop.shopify_domain
    )

    return {"status": "completed", "stats": stats}


@router.get("/import/status/{job_id}")
async def get_import_status(job_id: str) -> dict[str, Any]:
    """Get status of a background import job.

    Args:
        job_id: Celery task ID

    Returns:
        Job status and progress
    """
    task_result = AsyncResult(job_id)

    response: dict[str, Any] = {
        "job_id": job_id,
        "status": task_result.state,
    }

    if task_result.state == "PENDING":
        response["message"] = "Task is waiting to start"
    elif task_result.state == "STARTED":
        response["message"] = "Task has started"
        if task_result.info:
            response["progress"] = task_result.info.get("progress", 0)
    elif task_result.state == "PROGRESS":
        if task_result.info:
            response["progress"] = task_result.info.get("progress", 0)
            response["message"] = task_result.info.get("status", "In progress")
            if "stats" in task_result.info:
                response["stats"] = task_result.info["stats"]
    elif task_result.state == "SUCCESS":
        response["message"] = "Import completed successfully"
        response["result"] = task_result.result
    elif task_result.state == "FAILURE":
        response["message"] = "Import failed"
        response["error"] = str(task_result.info)

    return response


@router.get("")
async def list_products(
    shop_id: int = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """List products for authenticated shop.

    Args:
        shop_id: Authenticated shop ID from JWT
        db: Database session
        skip: Number of records to skip
        limit: Maximum number of records to return

    Returns:
        List of products with pagination
    """
    result = await db.execute(
        select(Product)
        .where(Product.shop_id == shop_id, Product.status == "active")
        .offset(skip)
        .limit(limit)
    )
    products = result.scalars().all()

    # Get total count
    count_result = await db.execute(
        select(Product).where(Product.shop_id == shop_id, Product.status == "active")
    )
    total = len(count_result.scalars().all())

    return {
        "products": [
            {
                "id": p.id,
                "shopify_product_id": p.shopify_product_id,
                "title": p.title,
                "handle": p.handle,
                "image_url": p.image_url,
                "our_price": float(p.our_price),
                "currency": p.currency,
                "tags": p.tags,
                "variants_count": len(p.variants) if p.variants else 0,
                "created_at": p.created_at.isoformat(),
            }
            for p in products
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/{product_id}")
async def get_product(
    product_id: int,
    shop_id: int = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a specific product.

    Args:
        product_id: Product database ID
        shop_id: Authenticated shop ID from JWT
        db: Database session

    Returns:
        Product details

    Raises:
        HTTPException: If product not found or doesn't belong to shop
    """
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.shop_id == shop_id)
    )
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    return {
        "id": product.id,
        "shopify_product_id": product.shopify_product_id,
        "title": product.title,
        "handle": product.handle,
        "image_url": product.image_url,
        "our_price": float(product.our_price),
        "currency": product.currency,
        "variants": product.variants,
        "tags": product.tags,
        "status": product.status,
        "created_at": product.created_at.isoformat(),
        "updated_at": product.updated_at.isoformat(),
    }


@router.delete("/{product_id}")
async def delete_product(
    product_id: int,
    shop_id: int = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Archive a product (soft delete).

    Args:
        product_id: Product database ID
        shop_id: Authenticated shop ID from JWT
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException: If product not found
    """
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.shop_id == shop_id)
    )
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    product.status = "archived"
    await db.commit()

    return {"message": "Product archived successfully"}
