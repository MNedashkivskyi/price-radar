"""Onboarding status API endpoints."""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from price_radar.api.middleware import get_current_shop_id
from price_radar.infrastructure.database import get_db
from price_radar.infrastructure.models import Competitor, CompetitorProduct, Product

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("/status")
async def get_onboarding_status(
    shop_id: int = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the current onboarding status for the shop.

    Derives status from actual data rather than storing flags.

    Args:
        shop_id: Authenticated shop ID from JWT
        db: Database session

    Returns:
        Current onboarding status with step completion info
    """
    # Step 1: Check if products are imported
    result = await db.execute(
        select(Product).where(Product.shop_id == shop_id, Product.status == "active").limit(1)
    )
    has_products = result.scalar_one_or_none() is not None

    # Step 2: Check if at least one competitor exists
    result = await db.execute(
        select(Competitor).where(
            Competitor.shop_id == shop_id, Competitor.status == "active"
        ).limit(1)
    )
    has_competitor = result.scalar_one_or_none() is not None

    # Step 3: Check if at least one mapping exists
    has_mappings = False
    if has_competitor:
        result = await db.execute(
            select(CompetitorProduct)
            .join(Competitor)
            .where(Competitor.shop_id == shop_id, CompetitorProduct.status == "active")
            .limit(1)
        )
        has_mappings = result.scalar_one_or_none() is not None

    # Determine current step
    if not has_products:
        current_step = 1
    elif not has_competitor:
        current_step = 2
    elif not has_mappings:
        current_step = 3
    else:
        current_step = 4  # Completed

    return {
        "current_step": current_step,
        "steps": [
            {"step": 1, "completed": has_products, "completed_at": None},
            {"step": 2, "completed": has_competitor, "completed_at": None},
            {"step": 3, "completed": has_mappings, "completed_at": None},
        ],
    }
