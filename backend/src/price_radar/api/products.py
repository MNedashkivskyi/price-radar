"""Product API endpoints."""

from typing import Any, Literal

from celery.result import AsyncResult  # type: ignore[import-untyped]
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from price_radar.api.middleware import get_current_shop_id
from price_radar.api.schemas import (
    ProductCreateRequest,
    ProductResponse,
    ProductUpdateRequest,
)
from price_radar.application.product_import_service import ProductImportService
from price_radar.application.shopify_service import ShopifyService
from price_radar.infrastructure.database import get_db
from price_radar.infrastructure.models import Competitor, CompetitorProduct, Product, Shop
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


@router.post("", response_model=ProductResponse, status_code=201)
async def create_product(
    product_data: ProductCreateRequest = Body(..., embed=False),
    shop_id: int = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
) -> Product:
    """Create a product manually (for non-Shopify products).

    Args:
        product_data: Product creation data
        shop_id: Authenticated shop ID from JWT
        db: Database session

    Returns:
        Created product

    Raises:
        HTTPException: If handle already exists or validation fails
    """
    # Check if handle already exists for this shop
    if product_data.handle:
        result = await db.execute(
            select(Product).where(
                Product.shop_id == shop_id,
                Product.handle == product_data.handle,
                Product.status == "active",
            )
        )
        existing_product = result.scalar_one_or_none()
        if existing_product:
            raise HTTPException(
                status_code=400,
                detail=f"Product with handle '{product_data.handle}' already exists",
            )

    # Create product
    product = Product(
        shop_id=shop_id,
        shopify_product_id=product_data.shopify_product_id,
        title=product_data.title,
        handle=product_data.handle,
        image_url=product_data.image_url,
        our_price=product_data.our_price,
        currency=product_data.currency,
        variants=product_data.variants,
        tags=product_data.tags,
        status="active",
    )

    db.add(product)
    await db.commit()
    await db.refresh(product)

    return product


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    product_data: ProductUpdateRequest = Body(..., embed=False),
    shop_id: int = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
) -> Product:
    """Update a product manually.

    Args:
        product_id: Product database ID
        product_data: Product update data (only provided fields will be updated)
        shop_id: Authenticated shop ID from JWT
        db: Database session

    Returns:
        Updated product

    Raises:
        HTTPException: If product not found or validation fails
    """
    # Get product
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.shop_id == shop_id)
    )
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Check if updating handle to one that already exists
    if product_data.handle and product_data.handle != product.handle:
        result = await db.execute(
            select(Product).where(
                Product.shop_id == shop_id,
                Product.handle == product_data.handle,
                Product.status == "active",
                Product.id != product_id,
            )
        )
        existing_product = result.scalar_one_or_none()
        if existing_product:
            raise HTTPException(
                status_code=400,
                detail=f"Product with handle '{product_data.handle}' already exists",
            )

    # Update only provided fields
    update_data = product_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(product, field, value)

    await db.commit()
    await db.refresh(product)

    return product


@router.get("")
async def list_products(
    shop_id: int = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    search: str | None = Query(None, max_length=200, description="Search by title or handle"),
    tag: str | None = Query(None, max_length=100, description="Filter by tag (case-insensitive)"),
    sort_by: Literal["title", "our_price", "created_at", "competitors_tracked"] = Query(
        "created_at", description="Column to sort by"
    ),
    sort_order: Literal["asc", "desc"] = Query("desc", description="Sort direction"),
) -> dict[str, Any]:
    """List products for authenticated shop with search, filter, sort, and competitor count.

    Args:
        shop_id: Authenticated shop ID from JWT
        db: Database session
        skip: Number of records to skip (pagination offset)
        limit: Maximum number of records to return (page size, max 100)
        search: Search term to filter by title or handle
        tag: Filter by products containing this tag (case-insensitive)
        sort_by: Column to sort by (title, our_price, created_at, competitors_tracked)
        sort_order: Sort direction (asc or desc)

    Returns:
        List of products with pagination, competitor counts, and all unique tags
    """
    # Build base filter
    base_where = [Product.shop_id == shop_id, Product.status == "active"]

    if search:
        search_pattern = f"%{search.lower()}%"
        base_where.append(
            func.lower(Product.title).like(search_pattern)
            | func.lower(Product.handle).like(search_pattern)
        )

    if tag:
        # Tags are stored as comma-separated text; do case-insensitive LIKE
        base_where.append(func.lower(Product.tags).like(f"%{tag.lower()}%"))

    # Subquery: count competitor_products per product
    competitor_count_sq = (
        select(
            CompetitorProduct.product_id,
            func.count(CompetitorProduct.id).label("competitors_tracked"),
        )
        .where(CompetitorProduct.status == "active")
        .group_by(CompetitorProduct.product_id)
        .subquery()
    )

    # Main query with LEFT JOIN to get competitor count
    query = (
        select(
            Product,
            func.coalesce(competitor_count_sq.c.competitors_tracked, 0).label(
                "competitors_tracked"
            ),
        )
        .outerjoin(competitor_count_sq, Product.id == competitor_count_sq.c.product_id)
        .where(*base_where)
    )

    # Apply sorting
    if sort_by == "competitors_tracked":
        sort_col = func.coalesce(competitor_count_sq.c.competitors_tracked, 0)
    elif sort_by == "title":
        sort_col = func.lower(Product.title)
    elif sort_by == "our_price":
        sort_col = Product.our_price
    else:
        sort_col = Product.created_at

    query = query.order_by(sort_col.desc() if sort_order == "desc" else sort_col.asc())

    # Total count (with filters applied)
    count_query = select(func.count()).select_from(
        select(Product.id).where(*base_where).subquery()
    )
    total = (await db.execute(count_query)).scalar() or 0

    # Fetch page
    rows = (await db.execute(query.offset(skip).limit(limit))).all()

    # Fetch competitor mappings for these products
    product_ids = [p.id for p, _ in rows]
    mappings_result = await db.execute(
        select(CompetitorProduct, Competitor)
        .join(Competitor, CompetitorProduct.competitor_id == Competitor.id)
        .where(
            CompetitorProduct.product_id.in_(product_ids),
            CompetitorProduct.status == "active",
        )
    )
    mappings_rows = mappings_result.all()

    # Organize mappings by product_id
    mappings_by_product: dict[int, list[dict[str, Any]]] = {}
    for cp, comp in mappings_rows:
        if cp.product_id not in mappings_by_product:
            mappings_by_product[cp.product_id] = []
        mappings_by_product[cp.product_id].append(
            {
                "competitor_id": comp.id,
                "competitor_name": comp.name,
                "competitor_domain": comp.domain,
                "url": cp.url,
            }
        )

    # Collect all unique tags across ALL products for this shop (for filter sidebar)
    all_tags_result = await db.execute(
        select(Product.tags).where(
            Product.shop_id == shop_id, Product.status == "active", Product.tags.isnot(None)
        )
    )
    tags_set: set[str] = set()
    for (raw_tags,) in all_tags_result:
        if raw_tags:
            for t in raw_tags.split(","):
                stripped = t.strip()
                if stripped:
                    tags_set.add(stripped)

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
                "competitors_tracked": ct,
                "competitor_urls": mappings_by_product.get(p.id, []),
                "created_at": p.created_at.isoformat(),
                "updated_at": p.updated_at.isoformat(),
            }
            for p, ct in rows
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
        "all_tags": sorted(tags_set),
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
