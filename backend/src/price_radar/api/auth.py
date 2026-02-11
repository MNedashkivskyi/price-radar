"""Authentication API endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from price_radar.api.middleware import get_current_shop_id
from price_radar.infrastructure.database import get_db
from price_radar.infrastructure.models import Shop

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
async def get_current_shop(
    shop_id: int = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get current authenticated shop information.

    This endpoint requires a valid JWT token in the Authorization header.

    Args:
        shop_id: Shop ID extracted from JWT token
        db: Database session

    Returns:
        Shop information

    Raises:
        HTTPException: If shop not found
    """
    result = await db.execute(select(Shop).where(Shop.id == shop_id))
    shop = result.scalar_one_or_none()

    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    return {
        "id": shop.id,
        "shopify_domain": shop.shopify_domain,
        "plan": shop.plan,
        "status": shop.status,
        "created_at": shop.created_at.isoformat(),
    }


@router.post("/refresh")
async def refresh_token(
    shop_id: int = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Refresh JWT session token.

    Generates a new JWT token for the authenticated shop.

    Args:
        shop_id: Shop ID extracted from JWT token
        db: Database session

    Returns:
        New JWT token

    Raises:
        HTTPException: If shop not found or inactive
    """
    from price_radar.application.jwt_service import JWTService

    result = await db.execute(select(Shop).where(Shop.id == shop_id))
    shop = result.scalar_one_or_none()

    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    if shop.status != "active":
        raise HTTPException(status_code=403, detail="Shop is not active")

    jwt_service = JWTService()
    new_token = jwt_service.create_session_token(shop.id, shop.shopify_domain)

    return {
        "access_token": new_token,
        "token_type": "bearer",
    }
