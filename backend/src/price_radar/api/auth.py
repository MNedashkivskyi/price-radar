"""Authentication API endpoints."""

from typing import Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from price_radar.api.middleware import get_current_shop_id
from price_radar.application.jwt_service import JWTService
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
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Refresh JWT session token.  Accepts expired tokens (up to 30 days old).

    The token's **signature** is still verified — only the expiration check is
    skipped so that users who return after >24 h can silently get a new JWT
    without going through Shopify OAuth again.

    Args:
        request: FastAPI request (we extract the bearer token manually)
        db: Database session

    Returns:
        New JWT token

    Raises:
        HTTPException: If token is missing/tampered/too old, or shop not found
    """
    # 1. Extract bearer token manually (no middleware validation)
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = auth_header.removeprefix("Bearer ")

    # 2. Verify signature but allow expired (up to 30 days)
    jwt_service = JWTService()
    try:
        payload = jwt_service.verify_token_allow_expired(token, max_age_days=30)
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    # 3. Verify shop still exists and is active
    shop_id = payload.get("shop_id")
    if not shop_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    result = await db.execute(select(Shop).where(Shop.id == int(shop_id)))
    shop = result.scalar_one_or_none()

    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    if shop.status != "active":
        raise HTTPException(status_code=403, detail="Shop is not active")

    # 4. Issue fresh token
    new_token = jwt_service.create_session_token(shop.id, shop.shopify_domain)

    return {
        "access_token": new_token,
        "token_type": "bearer",
    }
