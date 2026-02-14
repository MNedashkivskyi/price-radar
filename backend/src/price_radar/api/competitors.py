"""Competitor API endpoints."""

import csv
import io
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from price_radar.api.middleware import get_current_shop_id
from price_radar.api.schemas import (
    BulkUploadRequest,
    BulkUploadResponse,
    CompetitorCreateRequest,
    CompetitorProductCreateRequest,
    CompetitorProductResponse,
    CompetitorResponse,
)
from price_radar.infrastructure.database import get_db
from price_radar.infrastructure.models import Competitor, CompetitorProduct, Product

router = APIRouter(prefix="/competitors", tags=["competitors"])


@router.get("/detect")
async def detect_competitor(
    url: str = "",
) -> dict[str, Any]:
    """Detect competitor information from a URL.

    Extracts domain and attempts to determine competitor name.

    Args:
        url: Product URL to analyze

    Returns:
        Detected competitor information
    """
    try:
        parsed = urlparse(url if url.startswith("http") else f"https://{url}")
        domain = (parsed.hostname or "").replace("www.", "")
        name_part = domain.split(".")[0] if domain else ""
        name = name_part.capitalize()
        logo_url = f"https://www.google.com/s2/favicons?domain={domain}&sz=64"

        return {
            "name": name,
            "domain": domain,
            "logo_url": logo_url,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse URL: {str(e)}") from e


@router.post("", response_model=CompetitorResponse, status_code=201)
async def create_competitor(
    competitor_data: CompetitorCreateRequest = Body(..., embed=False),
    shop_id: int = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
) -> Competitor:
    """Create a new competitor.

    Args:
        competitor_data: Competitor creation data
        shop_id: Authenticated shop ID from JWT
        db: Database session

    Returns:
        Created competitor

    Raises:
        HTTPException: If competitor with same domain already exists
    """
    # Check if competitor with same domain already exists for this shop
    result = await db.execute(
        select(Competitor).where(
            Competitor.shop_id == shop_id,
            Competitor.domain == competitor_data.domain,
            Competitor.status == "active",
        )
    )
    existing_competitor = result.scalar_one_or_none()

    if existing_competitor:
        raise HTTPException(
            status_code=400,
            detail=f"Competitor with domain '{competitor_data.domain}' already exists",
        )

    # Create competitor
    competitor = Competitor(
        shop_id=shop_id,
        name=competitor_data.name,
        domain=competitor_data.domain,
        logo_url=competitor_data.logo_url,
        status="active",
    )

    db.add(competitor)
    await db.commit()
    await db.refresh(competitor)

    return competitor


@router.get("", response_model=list[CompetitorResponse])
async def list_competitors(
    shop_id: int = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
) -> list[Competitor]:
    """List all competitors for authenticated shop.

    Args:
        shop_id: Authenticated shop ID from JWT
        db: Database session

    Returns:
        List of competitors
    """
    result = await db.execute(
        select(Competitor).where(Competitor.shop_id == shop_id, Competitor.status == "active")
    )
    competitors = result.scalars().all()

    return list(competitors)


@router.post("/products", response_model=CompetitorProductResponse, status_code=201)
async def create_competitor_product(
    mapping_data: CompetitorProductCreateRequest = Body(..., embed=False),
    shop_id: int = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
) -> CompetitorProduct:
    """Add a single competitor product URL mapping.

    Args:
        mapping_data: Competitor product mapping data
        shop_id: Authenticated shop ID from JWT
        db: Database session

    Returns:
        Created competitor product mapping

    Raises:
        HTTPException: If product or competitor not found, or mapping already exists
    """
    # Verify product exists and belongs to shop
    result = await db.execute(
        select(Product).where(Product.id == mapping_data.product_id, Product.shop_id == shop_id)
    )
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail=f"Product {mapping_data.product_id} not found")

    # Verify competitor exists and belongs to shop
    result = await db.execute(
        select(Competitor).where(
            Competitor.id == mapping_data.competitor_id, Competitor.shop_id == shop_id
        )
    )
    competitor = result.scalar_one_or_none()

    if not competitor:
        raise HTTPException(
            status_code=404, detail=f"Competitor {mapping_data.competitor_id} not found"
        )

    # Check if mapping already exists
    result = await db.execute(
        select(CompetitorProduct).where(
            CompetitorProduct.product_id == mapping_data.product_id,
            CompetitorProduct.competitor_id == mapping_data.competitor_id,
            CompetitorProduct.status == "active",
        )
    )
    existing_mapping = result.scalar_one_or_none()

    if existing_mapping:
        raise HTTPException(
            status_code=400,
            detail="Mapping between this product and competitor already exists",
        )

    # Create competitor product mapping
    competitor_product = CompetitorProduct(
        product_id=mapping_data.product_id,
        competitor_id=mapping_data.competitor_id,
        url=mapping_data.url,
        selector_config=mapping_data.selector_config or {},
        status="active",
    )

    db.add(competitor_product)
    await db.commit()
    await db.refresh(competitor_product)

    return competitor_product


@router.post("/products/bulk", response_model=BulkUploadResponse)
async def bulk_upload_competitor_products(
    upload_data: BulkUploadRequest = Body(..., embed=False),
    shop_id: int = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Bulk upload competitor product mappings via CSV.

    CSV format: product_id, competitor_url
    or: sku, competitor_url (will look up product by handle/sku)

    Auto-detects competitor domain from URL and creates competitor if new.

    Args:
        upload_data: CSV data
        shop_id: Authenticated shop ID from JWT
        db: Database session

    Returns:
        Upload results with success/error counts
    """
    # Parse CSV
    csv_file = io.StringIO(upload_data.csv_data)
    reader = csv.DictReader(csv_file)

    success_count = 0
    error_count = 0
    errors: list[dict[str, Any]] = []
    created_competitors: set[str] = set()

    # Cache competitors to reduce DB queries
    competitors_cache: dict[str, Competitor] = {}

    # Load all products for this shop
    result = await db.execute(select(Product).where(Product.shop_id == shop_id))
    all_products = result.scalars().all()
    products_by_id = {p.id: p for p in all_products}
    products_by_handle = {p.handle: p for p in all_products if p.handle}

    # Load all competitors for this shop
    result = await db.execute(select(Competitor).where(Competitor.shop_id == shop_id))
    all_competitors = result.scalars().all()
    for comp in all_competitors:
        competitors_cache[comp.domain] = comp

    row_number = 1
    for row in reader:
        row_number += 1

        try:
            # Get product_id or sku/handle
            product_id_str = row.get("product_id", "").strip()
            sku = row.get("sku", "").strip()
            competitor_url = row.get("competitor_url", "").strip()

            if not competitor_url:
                errors.append(
                    {"row": row_number, "error": "competitor_url is required", "data": row}
                )
                error_count += 1
                continue

            # Find product
            product = None
            if product_id_str:
                try:
                    product_id = int(product_id_str)
                    product = products_by_id.get(product_id)
                except ValueError:
                    errors.append(
                        {
                            "row": row_number,
                            "error": f"Invalid product_id: {product_id_str}",
                            "data": row,
                        }
                    )
                    error_count += 1
                    continue
            elif sku:
                product = products_by_handle.get(sku)

            if not product:
                errors.append(
                    {
                        "row": row_number,
                        "error": f"Product not found: {product_id_str or sku}",
                        "data": row,
                    }
                )
                error_count += 1
                continue

            # Extract domain from URL
            try:
                parsed_url = urlparse(competitor_url)
                domain = parsed_url.netloc.lower().replace("www.", "")

                if not domain:
                    raise ValueError("Could not extract domain from URL")
            except Exception as e:
                errors.append(
                    {
                        "row": row_number,
                        "error": f"Invalid URL format: {str(e)}",
                        "data": row,
                    }
                )
                error_count += 1
                continue

            # Get or create competitor
            competitor = competitors_cache.get(domain)

            if not competitor:
                # Auto-create competitor
                competitor = Competitor(
                    shop_id=shop_id,
                    name=domain.split(".")[0].title(),  # e.g., amazon.com -> Amazon
                    domain=domain,
                    status="active",
                )
                db.add(competitor)
                await db.flush()  # Get ID without committing
                await db.refresh(competitor)

                competitors_cache[domain] = competitor
                created_competitors.add(domain)

            # Check if mapping already exists
            result = await db.execute(
                select(CompetitorProduct).where(
                    CompetitorProduct.product_id == product.id,
                    CompetitorProduct.competitor_id == competitor.id,
                    CompetitorProduct.status == "active",
                )
            )
            existing_mapping = result.scalar_one_or_none()

            if existing_mapping:
                # Update URL if different
                if existing_mapping.url != competitor_url:
                    existing_mapping.url = competitor_url
                success_count += 1
            else:
                # Create new mapping
                competitor_product = CompetitorProduct(
                    product_id=product.id,
                    competitor_id=competitor.id,
                    url=competitor_url,
                    selector_config={},
                    status="active",
                )
                db.add(competitor_product)
                success_count += 1

        except Exception as e:
            errors.append({"row": row_number, "error": str(e), "data": row})
            error_count += 1

    # Commit all changes
    await db.commit()

    return {
        "success_count": success_count,
        "error_count": error_count,
        "errors": errors,
        "created_competitors": list(created_competitors),
    }
