"""Shopify OAuth and API service."""

import hashlib
import hmac
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet  # type: ignore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from price_radar.domain.shopify import ShopifyStore
from price_radar.infrastructure.config import settings
from price_radar.infrastructure.models import Shop


class ShopifyService:
    """Service for Shopify OAuth and API operations."""

    def __init__(self, db: AsyncSession, encryption_key: bytes | None = None) -> None:
        """Initialize Shopify service.

        Args:
            db: Database session
            encryption_key: Key for encrypting access tokens (generates if None)
        """
        self.db = db
        self.api_key = settings.shopify_api_key
        self.api_secret = settings.shopify_api_secret
        self.app_url = settings.shopify_app_url
        self.scopes = settings.shopify_scopes
        self.api_version = settings.shopify_api_version

        # Use environment variable or generate encryption key
        self.encryption_key = encryption_key or Fernet.generate_key()
        self.cipher = Fernet(self.encryption_key)

    def generate_install_url(self, shop_domain: str, state: str | None = None) -> str:
        """Generate OAuth installation URL.

        Args:
            shop_domain: Shop domain (e.g., 'myshop.myshopify.com')
            state: Optional state parameter for CSRF protection

        Returns:
            Installation URL for shop owner to authorize app
        """
        if not shop_domain.endswith(".myshopify.com"):
            shop_domain = f"{shop_domain}.myshopify.com"

        app_url = self.app_url if self.app_url.startswith("http") else f"https://{self.app_url}"
        redirect_uri = f"{app_url}/api/shopify/callback"
        nonce = state or secrets.token_urlsafe(16)

        params = {
            "client_id": self.api_key,
            "scope": self.scopes,
            "redirect_uri": redirect_uri,
            "state": nonce,
        }

        return f"https://{shop_domain}/admin/oauth/authorize?{urlencode(params)}"

    def verify_hmac(self, query_params: dict[str, str]) -> bool:
        """Verify HMAC signature from Shopify.

        Args:
            query_params: Query parameters from callback

        Returns:
            True if HMAC is valid
        """
        hmac_to_verify = query_params.get("hmac", "")
        if not hmac_to_verify:
            return False

        # Remove hmac from params for verification
        params = {k: v for k, v in query_params.items() if k != "hmac"}

        # Sort and encode parameters
        encoded_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()))

        # Calculate HMAC
        computed_hmac = hmac.new(
            self.api_secret.encode("utf-8"),
            encoded_params.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(computed_hmac, hmac_to_verify)

    async def exchange_code_for_token(self, shop_domain: str, code: str) -> str:
        """Exchange authorization code for access token.

        Args:
            shop_domain: Shop domain
            code: Authorization code from callback

        Returns:
            Access token

        Raises:
            httpx.HTTPError: If token exchange fails
        """
        url = f"https://{shop_domain}/admin/oauth/access_token"
        payload = {
            "client_id": self.api_key,
            "client_secret": self.api_secret,
            "code": code,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            return str(data["access_token"])

    def encrypt_token(self, token: str) -> str:
        """Encrypt access token for storage.

        Args:
            token: Plain text access token

        Returns:
            Encrypted token
        """
        return str(self.cipher.encrypt(token.encode()).decode())

    def decrypt_token(self, encrypted_token: str) -> str:
        """Decrypt access token from storage.

        Args:
            encrypted_token: Encrypted token

        Returns:
            Plain text access token
        """
        return str(self.cipher.decrypt(encrypted_token.encode()).decode())

    async def save_store(self, store: ShopifyStore) -> Shop:
        """Save or update shop in database.

        Args:
            store: Shopify store domain object

        Returns:
            Database model
        """
        # Check if store exists
        result = await self.db.execute(select(Shop).where(Shop.shopify_domain == store.shop_domain))
        db_store = result.scalar_one_or_none()

        encrypted_token = self.encrypt_token(store.access_token)

        if db_store:
            # Update existing store
            db_store.access_token = encrypted_token
            db_store.status = "active"
        else:
            # Create new store
            db_store = Shop(
                shopify_domain=store.shop_domain,
                access_token=encrypted_token,
                plan="free",
                status="active",
            )
            self.db.add(db_store)

        await self.db.commit()
        await self.db.refresh(db_store)
        return db_store

    async def get_store(self, shop_domain: str) -> ShopifyStore | None:
        """Get store from database.

        Args:
            shop_domain: Shop domain

        Returns:
            Store domain object or None if not found
        """
        result = await self.db.execute(select(Shop).where(Shop.shopify_domain == shop_domain))
        db_store = result.scalar_one_or_none()

        if not db_store:
            return None

        access_token = self.decrypt_token(db_store.access_token)

        return ShopifyStore(
            store_id=db_store.id,
            shop_domain=db_store.shopify_domain,
            access_token=access_token,
            scopes=self.scopes,  # Use the service's configured scopes
            installed_at=db_store.created_at,
        )

    async def make_api_request(
        self,
        shop_domain: str,
        endpoint: str,
        method: str = "GET",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make authenticated API request to Shopify.

        Args:
            shop_domain: Shop domain
            endpoint: API endpoint (e.g., '/products.json')
            method: HTTP method
            data: Request body for POST/PUT

        Returns:
            API response data

        Raises:
            ValueError: If store not found
            httpx.HTTPError: If request fails
        """
        store = await self.get_store(shop_domain)
        if not store:
            raise ValueError(f"Store not found: {shop_domain}")

        url = f"https://{shop_domain}/admin/api/{self.api_version}{endpoint}"
        headers = {"X-Shopify-Access-Token": store.access_token}

        async with httpx.AsyncClient() as client:
            if method == "GET":
                response = await client.get(url, headers=headers)
            elif method == "POST":
                response = await client.post(url, headers=headers, json=data)
            elif method == "PUT":
                response = await client.put(url, headers=headers, json=data)
            elif method == "DELETE":
                response = await client.delete(url, headers=headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]
