"""Shopify OAuth API endpoints."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from price_radar.application.jwt_service import JWTService
from price_radar.application.shopify_service import ShopifyService
from price_radar.domain.shopify import ShopifyStore
from price_radar.infrastructure.config import settings
from price_radar.infrastructure.database import get_db

router = APIRouter(prefix="/shopify", tags=["shopify"])


def get_shopify_service(db: AsyncSession = Depends(get_db)) -> ShopifyService:
    """Get Shopify service dependency."""
    return ShopifyService(db)


@router.get("/install")
async def install_app(
    shop: str = Query(..., description="Shop domain (e.g., myshop.myshopify.com)"),
    service: ShopifyService = Depends(get_shopify_service),
) -> RedirectResponse:
    """Initiate Shopify app installation.

    This endpoint generates the OAuth authorization URL and redirects the user
    to Shopify to authorize the app installation.

    Args:
        shop: Shop domain
        service: Shopify service

    Returns:
        Redirect to Shopify authorization page
    """
    # Normalize shop domain
    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"

    # Generate installation URL
    install_url = service.generate_install_url(shop)

    return RedirectResponse(url=install_url)


@router.get("/callback")
async def oauth_callback(
    request: Request,
    shop: str = Query(..., description="Shop domain"),
    code: str = Query(..., description="Authorization code"),
    state: str | None = Query(None, description="State parameter"),
    hmac: str = Query(..., description="HMAC signature"),
    service: ShopifyService = Depends(get_shopify_service),
) -> RedirectResponse:
    """Handle OAuth callback from Shopify.

    After the shop owner authorizes the app, Shopify redirects to this endpoint
    with an authorization code. We exchange the code for an access token,
    store it in the database, generate a JWT session token, and redirect to the
    frontend dashboard.

    Args:
        request: FastAPI request object
        shop: Shop domain
        code: Authorization code
        state: State parameter for CSRF protection
        hmac: HMAC signature for verification
        service: Shopify service

    Returns:
        Redirect to frontend dashboard with JWT token

    Raises:
        HTTPException: If HMAC verification fails or token exchange fails
    """
    # Verify HMAC signature
    query_params = dict(request.query_params)
    if not service.verify_hmac(query_params):
        raise HTTPException(status_code=403, detail="Invalid HMAC signature")

    try:
        # Exchange code for access token
        access_token = await service.exchange_code_for_token(shop, code)

        # Create store domain object
        store = ShopifyStore(
            shop_domain=shop,
            access_token=access_token,
            scopes=service.scopes,
            installed_at=datetime.utcnow(),
        )

        # Save to database
        db_shop = await service.save_store(store)

        # Generate JWT session token
        jwt_service = JWTService()
        session_token = jwt_service.create_session_token(db_shop.id, db_shop.shopify_domain)

        # Redirect to frontend onboarding with JWT token as query parameter
        redirect_url = f"{settings.frontend_url}/onboarding?token={session_token}"
        return RedirectResponse(url=redirect_url, status_code=302)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Installation failed: {str(e)}") from e


@router.get("/stores/{shop_domain}")
async def get_store_info(
    shop_domain: str,
    service: ShopifyService = Depends(get_shopify_service),
) -> dict[str, Any]:
    """Get store information.

    Args:
        shop_domain: Shop domain
        service: Shopify service

    Returns:
        Store information

    Raises:
        HTTPException: If store not found
    """
    store = await service.get_store(shop_domain)
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    return {
        "shop_domain": store.shop_domain,
        "scopes": store.scopes,
        "is_active": store.is_active(),
        "installed_at": store.installed_at.isoformat(),
    }


@router.get("/stores/{shop_domain}/products")
async def get_products(
    shop_domain: str,
    limit: int = Query(50, ge=1, le=250),
    service: ShopifyService = Depends(get_shopify_service),
) -> dict[str, Any]:
    """Get products from Shopify store.

    Args:
        shop_domain: Shop domain
        limit: Number of products to return
        service: Shopify service

    Returns:
        Products data from Shopify API

    Raises:
        HTTPException: If request fails
    """
    try:
        products = await service.make_api_request(
            shop_domain, f"/products.json?limit={limit}", method="GET"
        )
        return products
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch products: {str(e)}") from e


@router.get("/stores/{shop_domain}/orders")
async def get_orders(
    shop_domain: str,
    limit: int = Query(50, ge=1, le=250),
    service: ShopifyService = Depends(get_shopify_service),
) -> dict[str, Any]:
    """Get orders from Shopify store.

    Args:
        shop_domain: Shop domain
        limit: Number of orders to return
        service: Shopify service

    Returns:
        Orders data from Shopify API

    Raises:
        HTTPException: If request fails
    """
    try:
        orders = await service.make_api_request(
            shop_domain, f"/orders.json?limit={limit}", method="GET"
        )
        return orders
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch orders: {str(e)}") from e
