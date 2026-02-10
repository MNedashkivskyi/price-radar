"""Shopify domain models."""

from datetime import datetime


class ShopifyStore:
    """Shopify store domain model."""

    def __init__(
        self,
        shop_domain: str,
        access_token: str,
        scopes: str,
        installed_at: datetime | None = None,
        store_id: int | None = None,
    ) -> None:
        """Initialize Shopify store.

        Args:
            shop_domain: The myshopify.com domain
            access_token: OAuth access token
            scopes: Comma-separated list of granted scopes
            installed_at: Installation timestamp
            store_id: Database ID
        """
        self.store_id = store_id
        self.shop_domain = shop_domain
        self.access_token = access_token
        self.scopes = scopes
        self.installed_at = installed_at or datetime.utcnow()

    def has_scope(self, scope: str) -> bool:
        """Check if store has a specific scope.

        Args:
            scope: Scope to check (e.g., 'read_products')

        Returns:
            True if scope is granted
        """
        return scope in self.scopes.split(",")

    def is_active(self) -> bool:
        """Check if store installation is active.

        Returns:
            True if access token exists
        """
        return bool(self.access_token)
