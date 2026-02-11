"""Service for importing products from Shopify."""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from price_radar.application.shopify_client import ShopifyAPIClient
from price_radar.infrastructure.models import Product


class ProductImportService:
    """Service for importing and syncing products from Shopify."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize product import service.

        Args:
            db: Database session
        """
        self.db = db

    async def import_products(
        self, shop_id: int, access_token: str, shop_domain: str
    ) -> dict[str, Any]:
        """Import all products from Shopify for a shop.

        Args:
            shop_id: Database ID of the shop
            access_token: Decrypted Shopify access token
            shop_domain: Shop's Shopify domain

        Returns:
            Import statistics
        """
        client = ShopifyAPIClient(shop_domain, access_token)

        # Get total count for progress tracking
        total_count = await client.get_product_count()

        stats = {
            "total_products": total_count,
            "imported": 0,
            "created": 0,
            "updated": 0,
            "errors": 0,
            "started_at": datetime.utcnow().isoformat(),
        }

        # Track existing products for sync
        existing_products = await self._get_existing_products(shop_id)
        seen_product_ids = set()

        # Paginate through all products
        page_info = None
        has_next = True

        while has_next:
            response = await client.get_products(limit=250, page_info=page_info)
            products = response["products"]
            has_next = response["has_next_page"]
            page_info = response["next_page_info"]

            for shopify_product in products:
                try:
                    await self._import_single_product(shop_id, shopify_product, existing_products)
                    stats["imported"] += 1

                    shopify_id = str(shopify_product["id"])
                    seen_product_ids.add(shopify_id)

                    if shopify_id in existing_products:
                        stats["updated"] += 1
                    else:
                        stats["created"] += 1

                except Exception as e:
                    stats["errors"] += 1
                    # Log error but continue with other products
                    print(f"Error importing product {shopify_product.get('id')}: {e}")

        # Mark products as archived if they no longer exist in Shopify
        for existing_id in existing_products:
            if existing_id not in seen_product_ids:
                await self._archive_product(existing_products[existing_id])

        await self.db.commit()

        stats["completed_at"] = datetime.utcnow().isoformat()
        return stats

    async def _import_single_product(
        self, shop_id: int, shopify_product: dict[str, Any], existing_products: dict[str, Product]
    ) -> Product:
        """Import or update a single product.

        Args:
            shop_id: Shop database ID
            shopify_product: Product data from Shopify API
            existing_products: Dictionary of existing products by Shopify ID

        Returns:
            Created or updated Product model
        """
        shopify_id = str(shopify_product["id"])

        # Extract product data
        title = shopify_product.get("title", "")
        handle = shopify_product.get("handle", "")
        image_url = None
        if shopify_product.get("images"):
            image_url = shopify_product["images"][0].get("src")

        # Get price from first variant
        our_price = 0.0
        variants_data = []
        if shopify_product.get("variants"):
            first_variant = shopify_product["variants"][0]
            our_price = float(first_variant.get("price", 0.0))

            # Store all variants as JSON
            for variant in shopify_product["variants"]:
                variants_data.append(
                    {
                        "id": variant.get("id"),
                        "title": variant.get("title"),
                        "price": variant.get("price"),
                        "sku": variant.get("sku"),
                        "inventory_quantity": variant.get("inventory_quantity"),
                    }
                )

        # Get tags
        tags = shopify_product.get("tags", "")

        # Check if product exists
        if shopify_id in existing_products:
            # Update existing product
            product = existing_products[shopify_id]
            product.title = title
            product.handle = handle
            product.image_url = image_url
            product.our_price = our_price
            product.variants = variants_data
            product.tags = tags
            product.status = "active"
        else:
            # Create new product
            product = Product(
                shop_id=shop_id,
                shopify_product_id=shopify_id,
                title=title,
                handle=handle,
                image_url=image_url,
                our_price=our_price,
                currency="USD",  # TODO: Get from shop settings
                variants=variants_data,
                tags=tags,
                status="active",
            )
            self.db.add(product)

        return product

    async def _get_existing_products(self, shop_id: int) -> dict[str, Product]:
        """Get all existing products for a shop.

        Args:
            shop_id: Shop database ID

        Returns:
            Dictionary mapping Shopify product ID to Product model
        """
        result = await self.db.execute(select(Product).where(Product.shop_id == shop_id))
        products = result.scalars().all()

        return {product.shopify_product_id: product for product in products}

    async def _archive_product(self, product: Product) -> None:
        """Mark a product as archived.

        Args:
            product: Product to archive
        """
        product.status = "archived"

    async def get_import_progress(self, shop_id: int) -> dict[str, Any]:
        """Get import progress for a shop.

        This would be enhanced to track actual import job progress.
        For now, returns product counts.

        Args:
            shop_id: Shop database ID

        Returns:
            Progress information
        """
        result = await self.db.execute(
            select(Product).where(Product.shop_id == shop_id, Product.status == "active")
        )
        active_products = result.scalars().all()

        return {
            "shop_id": shop_id,
            "total_products": len(active_products),
            "status": "completed",  # Would track actual job status
        }
