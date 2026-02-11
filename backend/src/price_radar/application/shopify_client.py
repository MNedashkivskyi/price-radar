"""Shopify API client for product operations."""

from typing import Any

import httpx

from backend.src.price_radar.infrastructure.config import settings


class ShopifyAPIClient:
    """Client for interacting with Shopify REST API."""

    def __init__(self, shop_domain: str, access_token: str) -> None:
        """Initialize Shopify API client.

        Args:
            shop_domain: Shop's Shopify domain (e.g., store.myshopify.com)
            access_token: OAuth access token for the shop
        """
        self.shop_domain = shop_domain
        self.access_token = access_token
        self.api_version = settings.shopify_api_version
        self.base_url = f"https://{shop_domain}/admin/api/{self.api_version}"

    async def get_products(self, limit: int = 250, page_info: str | None = None) -> dict[str, Any]:
        """Fetch products from Shopify API with pagination.

        Uses cursor-based pagination for efficiency with large catalogs.

        Args:
            limit: Number of products per page (max 250)
            page_info: Page cursor for pagination (from previous response)

        Returns:
            Dictionary containing products list and pagination info

        Raises:
            httpx.HTTPError: If API request fails
        """
        headers = {"X-Shopify-Access-Token": self.access_token}

        params: dict[str, Any] = {"limit": min(limit, 250)}

        if page_info:
            params["page_info"] = page_info

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/products.json", headers=headers, params=params, timeout=30.0
            )
            response.raise_for_status()

            # Extract Link header for pagination
            link_header = response.headers.get("Link", "")
            next_page_info = self._extract_next_page_info(link_header)

            data = response.json()
            return {
                "products": data.get("products", []),
                "next_page_info": next_page_info,
                "has_next_page": next_page_info is not None,
            }

    async def get_product_count(self) -> int:
        """Get total product count for the shop.

        Returns:
            Total number of products
        """
        headers = {"X-Shopify-Access-Token": self.access_token}

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/products/count.json", headers=headers, timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
            return int(data.get("count", 0))

    async def get_product(self, product_id: str) -> dict[str, Any]:
        """Fetch a single product by ID.

        Args:
            product_id: Shopify product ID

        Returns:
            Product data
        """
        headers = {"X-Shopify-Access-Token": self.access_token}

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/products/{product_id}.json", headers=headers, timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
            return dict(data.get("product", {}))

    def _extract_next_page_info(self, link_header: str) -> str | None:
        """Extract next page_info from Link header.

        Shopify uses cursor-based pagination via Link headers.

        Args:
            link_header: Value of Link header from response

        Returns:
            Next page info cursor or None if no next page
        """
        if not link_header:
            return None

        # Link header format: <url>; rel="next"
        links = link_header.split(",")
        for link in links:
            if 'rel="next"' in link:
                # Extract URL from <...>
                url_part = link.split(";")[0].strip()
                url = url_part.strip("<>")

                # Extract page_info parameter
                if "page_info=" in url:
                    page_info = url.split("page_info=")[1].split("&")[0]
                    return page_info

        return None
