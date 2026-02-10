"""Shopify OAuth API endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from price_radar.application.shopify_service import ShopifyService
from price_radar.domain.shopify import ShopifyStore
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
) -> HTMLResponse:
    """Handle OAuth callback from Shopify.

    After the shop owner authorizes the app, Shopify redirects to this endpoint
    with an authorization code. We exchange the code for an access token and
    store it in the database.

    Args:
        request: FastAPI request object
        shop: Shop domain
        code: Authorization code
        state: State parameter for CSRF protection
        hmac: HMAC signature for verification
        service: Shopify service

    Returns:
        HTML response confirming installation

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
        await service.save_store(store)

        # Return success page
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Installation Complete</title>
                <style>
                    body {{
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                            Oxygen, Ubuntu, Cantarell, sans-serif;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        height: 100vh;
                        margin: 0;
                        background-color: #f4f6f8;
                    }}
                    .container {{
                        text-align: center;
                        padding: 40px;
                        background: white;
                        border-radius: 8px;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    }}
                    .success {{
                        color: #008060;
                        font-size: 48px;
                        margin-bottom: 20px;
                    }}
                    h1 {{
                        color: #202223;
                        margin-bottom: 10px;
                    }}
                    p {{
                        color: #6d7175;
                        margin-bottom: 30px;
                    }}
                    .shop-info {{
                        background: #f4f6f8;
                        padding: 15px;
                        border-radius: 4px;
                        margin: 20px 0;
                    }}
                    .button {{
                        display: inline-block;
                        padding: 12px 24px;
                        background: #008060;
                        color: white;
                        text-decoration: none;
                        border-radius: 4px;
                        font-weight: 500;
                    }}
                    .button:hover {{
                        background: #006e52;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="success">✓</div>
                    <h1>Installation Complete!</h1>
                    <p>Price Radar has been successfully installed on your store.</p>
                    <div class="shop-info">
                        <strong>Store:</strong> {shop}
                    </div>
                    <a href="https://{shop}/admin/apps" class="button">
                        Go to Shopify Admin
                    </a>
                </div>
            </body>
            </html>
            """,
            status_code=200,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Installation failed: {str(e)}") from e


@router.get("/stores/{shop_domain}")
async def get_store_info(
    shop_domain: str,
    service: ShopifyService = Depends(get_shopify_service),
) -> dict:
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
) -> dict:
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
) -> dict:
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
