"""Strategy 6: Extract prices from embedded script data (__NEXT_DATA__, __INITIAL_STATE__, etc.).

Many modern SPAs (Next.js, Nuxt.js, React+Redux) embed their full page data in
<script> tags as JSON. This strategy mines those embedded payloads for price
information without needing JavaScript rendering.

Covers:
  - Next.js: <script id="__NEXT_DATA__" type="application/json">
  - React/Redux: window.__INITIAL_STATE__ / window.__PRELOADED_STATE__
  - Nuxt.js: window.__NUXT__ / <script id="__NUXT_DATA__">
  - Shopify inline: window.ShopifyAnalytics / var meta = {...}
  - Generic: window.__APP_STATE__, window.__DATA__, etc.
"""

from __future__ import annotations

import json
import logging
import re
from decimal import Decimal
from typing import Any

from bs4 import BeautifulSoup

from price_radar.application.price_extraction.normalizer import (
    normalize_currency_code,
    parse_price,
)
from price_radar.application.price_extraction.result import PriceData
from price_radar.application.price_extraction.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

# Keys that typically contain the current price
_PRICE_KEYS = frozenset({
    "price", "current_price", "currentprice", "saleprice", "sale_price",
    "finalprice", "final_price", "offerprice", "offer_price",
    "specialprice", "special_price", "displayprice", "display_price",
    "sellingprice", "selling_price", "regularprice", "regular_price",
    "listprice", "list_price", "amount", "priceamount", "price_amount",
    "unitprice", "unit_price", "minprice", "min_price", "lowprice", "low_price",
    "pricevalue", "price_value",
})

# Keys for original / compare-at price
_ORIGINAL_PRICE_KEYS = frozenset({
    "compareatprice", "compare_at_price", "compareAtPrice",
    "originalprice", "original_price", "originalPrice",
    "regularprice", "regular_price", "regularPrice",
    "listprice", "list_price", "listPrice",
    "msrp", "rrp", "wasPrice", "was_price",
    "beforeprice", "before_price",
})

# Keys for currency
_CURRENCY_KEYS = frozenset({
    "currency", "currencycode", "currency_code", "currencyCode",
    "pricecurrency", "priceCurrency", "price_currency",
    "isocurrencycode", "iso_currency_code",
})

# Keys indicating stock availability
_STOCK_KEYS = frozenset({
    "available", "instock", "in_stock", "inStock", "is_available",
    "isAvailable", "availability", "stockstatus", "stock_status",
    "purchasable", "isPurchasable", "is_purchasable",
})

# Maximum recursion depth to prevent stack overflow on deeply nested payloads
_MAX_DEPTH = 15

# Patterns to extract JSON from inline <script> tags
_INLINE_JSON_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("__INITIAL_STATE__", re.compile(
        r"window\.__INITIAL_STATE__\s*=\s*(\{.+?\})\s*;", re.DOTALL
    )),
    ("__PRELOADED_STATE__", re.compile(
        r"window\.__PRELOADED_STATE__\s*=\s*(\{.+?\})\s*;", re.DOTALL
    )),
    ("__APP_STATE__", re.compile(
        r"window\.__APP_STATE__\s*=\s*(\{.+?\})\s*;", re.DOTALL
    )),
    ("__NUXT__", re.compile(
        r"window\.__NUXT__\s*=\s*(\{.+?\})\s*;", re.DOTALL
    )),
    ("__DATA__", re.compile(
        r"window\.__DATA__\s*=\s*(\{.+?\})\s*;", re.DOTALL
    )),
]


class ScriptTagStrategy(BaseStrategy):
    """Extract prices from embedded JavaScript data payloads.

    Priority order:
    1. <script id="__NEXT_DATA__">  (Next.js SSR)
    2. window.__INITIAL_STATE__ etc. (Redux/React/Nuxt)
    3. Shopify-specific inline script data
    """

    name = "script_tag"

    def extract(self, soup: BeautifulSoup, url: str) -> PriceData | None:
        # 1. Try __NEXT_DATA__ (most reliable — full SSR data)
        result = self._extract_next_data(soup, url)
        if result:
            return result

        # 2. Try Nuxt.js <script id="__NUXT_DATA__">
        result = self._extract_nuxt_data(soup, url)
        if result:
            return result

        # 3. Try inline window.__*__ patterns
        result = self._extract_inline_state(soup, url)
        if result:
            return result

        # 4. Try Shopify-specific inline scripts
        result = self._extract_shopify_inline(soup, url)
        if result:
            return result

        return None

    # ── __NEXT_DATA__ ─────────────────────────────────────────────────

    def _extract_next_data(self, soup: BeautifulSoup, url: str) -> PriceData | None:
        """Parse Next.js __NEXT_DATA__ payload."""
        script = soup.find("script", id="__NEXT_DATA__")
        if not script or not script.string:
            return None

        try:
            data = json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            return None

        # Navigate into props.pageProps where product data usually lives
        page_props = data.get("props", {}).get("pageProps", {})
        if not page_props:
            # Some sites put data at top level or in different structure
            page_props = data

        return self._search_for_price(page_props)

    # ── __NUXT_DATA__ ─────────────────────────────────────────────────

    def _extract_nuxt_data(self, soup: BeautifulSoup, url: str) -> PriceData | None:
        """Parse Nuxt.js __NUXT_DATA__ payload."""
        script = soup.find("script", id="__NUXT_DATA__")
        if not script or not script.string:
            return None

        try:
            data = json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            return None

        return self._search_for_price(data)

    # ── Inline state (window.__*__) ────────────────────────────────────

    def _extract_inline_state(self, soup: BeautifulSoup, url: str) -> PriceData | None:
        """Search <script> tags for window.__*__ state assignments."""
        for script in soup.find_all("script"):
            if not script.string:
                continue

            text = script.string
            for label, pattern in _INLINE_JSON_PATTERNS:
                match = pattern.search(text)
                if not match:
                    continue
                try:
                    data = json.loads(match.group(1))
                except (json.JSONDecodeError, TypeError):
                    continue
                result = self._search_for_price(data)
                if result:
                    logger.debug("Found price in %s payload", label)
                    return result

        return None

    # ── Shopify inline ────────────────────────────────────────────────

    def _extract_shopify_inline(self, soup: BeautifulSoup, url: str) -> PriceData | None:
        """Extract prices from Shopify inline script data.

        Shopify pages often embed product data in various script formats:
        - window.ShopifyAnalytics.meta.product
        - var meta = { ... product: { ... } }
        - productJSON or productData assignments
        """
        for script in soup.find_all("script"):
            if not script.string:
                continue

            text = script.string

            # Pattern 1: Look for product variant JSON objects
            # Shopify often has: "variants":[{"id":..,"price":"2999",...}]
            variant_match = re.search(
                r'"variants"\s*:\s*(\[\{.+?\}\])', text, re.DOTALL
            )
            if variant_match:
                try:
                    variants = json.loads(variant_match.group(1))
                    if isinstance(variants, list) and variants:
                        return self._parse_shopify_variant(variants[0])
                except (json.JSONDecodeError, TypeError):
                    pass

            # Pattern 2: var meta = {...} with product info
            meta_match = re.search(
                r'var\s+meta\s*=\s*(\{.+?\})\s*;', text, re.DOTALL
            )
            if meta_match:
                try:
                    data = json.loads(meta_match.group(1))
                    if "product" in data:
                        result = self._search_for_price(data["product"])
                        if result:
                            return result
                except (json.JSONDecodeError, TypeError):
                    pass

        return None

    def _parse_shopify_variant(self, variant: dict[str, Any]) -> PriceData | None:
        """Parse a Shopify variant object into PriceData.

        Shopify stores prices in cents as strings: "price": "2999" means $29.99
        """
        price_raw = variant.get("price")
        if price_raw is None:
            return None

        # Shopify prices are sometimes in cents (no decimal point, > 100)
        price_str = str(price_raw)
        price_val = parse_price(price_str)

        if price_val is None or price_val <= 0:
            return None

        # Heuristic: if the price is a whole number > 100 and has no decimal,
        # it's likely in cents (Shopify format)
        if "." not in price_str and "," not in price_str and price_val >= 100:
            price_val = price_val / 100

        # Compare-at price
        compare_raw = variant.get("compare_at_price")
        original_price = None
        if compare_raw:
            compare_str = str(compare_raw)
            original_price = parse_price(compare_str)
            if original_price and "." not in compare_str and "," not in compare_str and original_price >= 100:
                original_price = original_price / 100

        # Availability
        available = variant.get("available")
        in_stock = bool(available) if available is not None else True

        return PriceData(
            current_price=price_val,
            original_price=original_price,
            in_stock=in_stock,
            strategy=self.name,
        )

    # ── Recursive price search ────────────────────────────────────────

    def _search_for_price(self, data: Any, depth: int = 0) -> PriceData | None:
        """Recursively search a JSON structure for price-like fields.

        Looks for known price keys at each level and tries to parse them.
        Returns the first valid price found, preferring objects that also
        contain currency and availability info.
        """
        if depth > _MAX_DEPTH:
            return None

        if isinstance(data, list):
            for item in data:
                result = self._search_for_price(item, depth + 1)
                if result:
                    return result
            return None

        if not isinstance(data, dict):
            return None

        # Try to extract price from THIS dict level
        result = self._try_extract_from_dict(data)
        if result:
            return result

        # Look for nested objects that might contain product/price data
        # Prioritize keys that are likely to be product-related
        priority_keys = [
            "product", "item", "productData", "productInfo",
            "pricing", "price", "priceInfo", "priceData",
            "offer", "offers", "buyBox", "buybox",
            "initialData", "data", "pageData", "content",
            "pdpData", "productDetail", "productDetails",
            "variants", "selectedVariant", "currentVariant",
            "initialZustandState", "dehydratedState",
        ]

        # Try priority keys first
        for key in priority_keys:
            if key in data:
                result = self._search_for_price(data[key], depth + 1)
                if result:
                    return result

        # Then try all remaining dict values (but limit to avoid explosion)
        checked = set(priority_keys)
        remaining = [(k, v) for k, v in data.items() if k not in checked]
        for key, value in remaining[:20]:  # Limit to 20 sub-keys
            if isinstance(value, (dict, list)):
                result = self._search_for_price(value, depth + 1)
                if result:
                    return result

        return None

    def _try_extract_from_dict(self, d: dict[str, Any]) -> PriceData | None:
        """Try to extract a PriceData from a single dict's fields."""
        # Find a price field
        price_val: Decimal | None = None
        for key in d:
            if key.lower().replace("-", "").replace("_", "") in _PRICE_KEYS:
                raw = d[key]
                if raw is None:
                    continue
                price_val = parse_price(str(raw))
                if price_val is not None and price_val > 0:
                    break
                price_val = None  # Reset if invalid

        if price_val is None:
            return None

        # Look for currency
        currency: str | None = None
        for key in d:
            if key.lower().replace("-", "").replace("_", "") in _CURRENCY_KEYS:
                raw = d[key]
                if raw and isinstance(raw, str) and len(raw) <= 5:
                    currency = normalize_currency_code(raw)
                    break

        # Look for availability
        in_stock: bool | None = None
        for key in d:
            if key.lower().replace("-", "").replace("_", "") in _STOCK_KEYS:
                raw = d[key]
                if isinstance(raw, bool):
                    in_stock = raw
                elif isinstance(raw, str):
                    lower = raw.lower()
                    if lower in ("true", "yes", "instock", "in_stock", "in stock", "1"):
                        in_stock = True
                    elif lower in ("false", "no", "outofstock", "out_of_stock", "out of stock", "0"):
                        in_stock = False
                break

        # Look for original / compare-at price
        original_price: Decimal | None = None
        for key in d:
            if key.lower().replace("-", "").replace("_", "") in _ORIGINAL_PRICE_KEYS:
                raw = d[key]
                if raw is not None:
                    original_price = parse_price(str(raw))
                    if original_price and original_price > 0:
                        break
                    original_price = None

        return PriceData(
            current_price=price_val,
            original_price=original_price,
            currency=currency,
            in_stock=in_stock,
            strategy=self.name,
        )
