"""Strategy 7: Shopify JSON API (/products/{handle}.json).

Shopify stores publicly expose a JSON endpoint for every product page:
    https://{store-domain}/products/{handle}.json

This endpoint requires no authentication and returns structured product data
including all variants with prices, compare-at prices, and availability.

This strategy makes an additional HTTP request, so it only activates when
the URL is detected as a Shopify store. Detection happens via:
  1. URL path matching (/products/{handle})
  2. HTML markers in the already-fetched page (Shopify CDN, meta tags)

Shopify stores prices in "money" format: "29.99" (not cents).
"""

from __future__ import annotations

import json
import logging
import re
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from price_radar.application.price_extraction.normalizer import (
    normalize_currency_code,
    parse_price,
)
from price_radar.application.price_extraction.result import PriceData
from price_radar.application.price_extraction.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

# Known Shopify custom domains (non-exhaustive, common ones)
_KNOWN_SHOPIFY_DOMAINS = frozenset({
    "gymshark.com",
    "allbirds.com",
    "fashionnova.com",
    "colourpop.com",
    "kylie.com",
    "kyliecosmetics.com",
    "jeffreestarcosmetics.com",
    "mvmtwatches.com",
    "bombas.com",
    "brooklinen.com",
    "chubbiesshorts.com",
    "puravidabracelets.com",
    "hauslabs.com",
    "skims.com",
    "fightcamp.com",
    "ruggable.com",
    "beistravel.com",
    "negativeunderwear.com",
    "trueclassictees.com",
    "drsquatch.com",
})

# HTTP headers for JSON API requests
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


class ShopifyApiStrategy(BaseStrategy):
    """Extract prices from Shopify's public product JSON API.

    This strategy:
    1. Detects if the page is a Shopify store (from HTML or URL)
    2. Extracts the product handle from the URL
    3. Fetches /products/{handle}.json
    4. Parses the first available variant's price

    Weight: 0.95 (very reliable when applicable — structured JSON from
    the platform itself, not scraped from rendered HTML).
    """

    name = "shopify_api"

    def __init__(self, timeout: int = 10) -> None:
        self._timeout = timeout

    def extract(self, soup: BeautifulSoup, url: str) -> PriceData | None:
        # Step 1: Is this a Shopify store?
        if not self._is_shopify(soup, url):
            return None

        # Step 2: Extract product handle from URL
        handle = self._extract_handle(url)
        if not handle:
            return None

        # Step 3: Build JSON API URL and fetch
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        json_url = f"{base_url}/products/{handle}.json"

        product_data = self._fetch_product_json(json_url)
        if not product_data:
            return None

        # Step 4: Parse the product data
        return self._parse_product(product_data)

    # ── Shopify Detection ─────────────────────────────────────────────

    def _is_shopify(self, soup: BeautifulSoup, url: str) -> bool:
        """Detect if the page belongs to a Shopify store."""
        parsed = urlparse(url)
        domain = parsed.netloc.lower().replace("www.", "")

        # 1. myshopify.com domain
        if "myshopify.com" in domain:
            return True

        # 2. Known Shopify custom domains
        if domain in _KNOWN_SHOPIFY_DOMAINS:
            return True
        # Check base domain (e.g. "gymshark.com" from "uk.gymshark.com")
        parts = domain.split(".")
        if len(parts) >= 2:
            base_domain = ".".join(parts[-2:])
            if base_domain in _KNOWN_SHOPIFY_DOMAINS:
                return True

        # 3. HTML-based detection (check the already-fetched page)
        # Look for Shopify CDN references
        page_text = str(soup)

        # Shopify CDN in asset URLs
        if "cdn.shopify.com" in page_text:
            return True

        # Shopify meta generator tag
        meta_gen = soup.find("meta", attrs={"name": "generator"})
        if meta_gen and "shopify" in str(meta_gen.get("content", "")).lower():
            return True

        # Shopify-specific script or link tags
        if "Shopify.theme" in page_text or "ShopifyAnalytics" in page_text:
            return True

        # Shopify checkout domain reference
        if "shopify_pay" in page_text or "/checkouts/" in page_text:
            # Weak signal but combined with /products/ URL it's enough
            if "/products/" in parsed.path:
                return True

        return False

    # ── Handle Extraction ─────────────────────────────────────────────

    @staticmethod
    def _extract_handle(url: str) -> str | None:
        """Extract the product handle from a Shopify product URL.

        Shopify product URLs follow the pattern:
            https://{domain}/products/{handle}
            https://{domain}/collections/{collection}/products/{handle}
        """
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")

        # Match /products/{handle}
        match = re.search(r"/products/([^/?#]+)", path)
        if match:
            handle = match.group(1)
            # Exclude known non-handle paths
            if handle not in ("", "all", "best-sellers", "new"):
                return handle

        return None

    # ── JSON API Fetch ────────────────────────────────────────────────

    def _fetch_product_json(self, json_url: str) -> dict[str, Any] | None:
        """Fetch product data from Shopify's public JSON API."""
        try:
            resp = httpx.get(
                json_url,
                headers=_HEADERS,
                follow_redirects=True,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("product")
        except httpx.HTTPStatusError as e:
            logger.debug("Shopify API HTTP %d for %s", e.response.status_code, json_url)
            return None
        except httpx.RequestError as e:
            logger.debug("Shopify API request error for %s: %s", json_url, e)
            return None
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.debug("Shopify API parse error for %s: %s", json_url, e)
            return None

    # ── Product Parsing ───────────────────────────────────────────────

    def _parse_product(self, product: dict[str, Any]) -> PriceData | None:
        """Parse a Shopify product JSON object into PriceData."""
        variants = product.get("variants", [])
        if not variants:
            return None

        # Find the first available variant, fallback to first variant
        variant = None
        for v in variants:
            if v.get("available", True):
                variant = v
                break

        if variant is None:
            variant = variants[0]

        # Parse price (Shopify returns "29.99" format, not cents)
        price_raw = variant.get("price")
        if price_raw is None:
            return None

        current_price = parse_price(str(price_raw))
        if current_price is None or current_price <= 0:
            return None

        # Compare-at price (original/was price)
        compare_raw = variant.get("compare_at_price")
        original_price = None
        if compare_raw:
            original_price = parse_price(str(compare_raw))
            if original_price is not None and original_price <= 0:
                original_price = None

        # Sale price: if compare_at exists and is higher, current is on sale
        sale_price = None
        if original_price and current_price and original_price > current_price:
            sale_price = current_price

        # Availability
        in_stock = variant.get("available", True)

        # Try to detect currency from product body or tags
        # Shopify doesn't include currency in the product JSON by default
        # We leave it as None so the orchestrator can fill it from other sources
        currency: str | None = None

        return PriceData(
            current_price=current_price,
            original_price=original_price,
            sale_price=sale_price,
            currency=currency,
            in_stock=bool(in_stock),
            strategy=self.name,
        )
