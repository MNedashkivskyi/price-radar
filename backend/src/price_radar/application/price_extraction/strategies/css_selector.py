"""Strategy: CSS selector configs per domain (stored in DB, hot-reloadable).

When no domain-specific config exists, an **auto-discovery** mode searches
the DOM for elements whose class/id contains "price", scores them by
proximity to product indicators, and returns the best candidate.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from price_radar.application.price_extraction.normalizer import (
    detect_currency,
    normalize_currency_code,
    parse_price,
)
from price_radar.application.price_extraction.result import PriceData
from price_radar.application.price_extraction.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

# Built-in CSS selector configs for top e-commerce platforms.
# These can be overridden or extended by per-domain configs stored in DB.
DEFAULT_SELECTOR_CONFIGS: dict[str, dict[str, str]] = {
    "amazon.com": {
        "price": ".a-price .a-offscreen, #priceblock_ourprice, #priceblock_dealprice, "
                 "span.a-color-price, #corePrice_feature_div .a-offscreen",
        "original_price": ".a-text-price .a-offscreen, .basisPrice .a-offscreen",
        "in_stock": "#availability span",
    },
    "ebay.com": {
        "price": ".x-price-primary span, .x-bin-price__content .ux-textspans, "
                 "[itemprop='price']",
        "original_price": ".x-price-approx__price span, .x-original-price span",
        "in_stock": ".d-quantity__availability span",
    },
    "walmart.com": {
        "price": "[itemprop='price'], span[data-automation-id='product-price'] span",
        "original_price": ".was-line-through span, .strike-through span",
        "in_stock": "[data-automation-id='add-to-cart-button']",
    },
    "target.com": {
        "price": "[data-test='product-price'] span, .styles__CurrentPriceFontSize",
        "original_price": "[data-test='product-regular-price'] span",
        "in_stock": "[data-test='add-to-cart-button']",
    },
    "bestbuy.com": {
        "price": ".priceView-customer-price span, .pricing-price__regular-price span",
        "original_price": ".pricing-price__regular-price span",
        "in_stock": ".add-to-cart-button",
    },
    "etsy.com": {
        "price": "[data-buy-box-listing-price], .wt-text-title-03",
        "original_price": ".wt-text-strikethrough",
        "in_stock": "[data-add-to-cart-button]",
    },
    "shopify.com": {
        "price": ".product__price .price-item--sale, .product__price .price-item--regular, "
                 ".price__sale .price-item--sale, .price .price-item",
        "original_price": ".price-item--regular.price-item--last, .price__compare-at",
        "in_stock": ".product-form__submit:not([disabled]), .add-to-cart:not([disabled])",
    },
    "aliexpress.com": {
        "price": ".product-price-value, .uniform-banner-box-price",
        "original_price": ".product-price-original, .uniform-banner-box-discountprice",
        "in_stock": "#root .add-to-cart",
    },
    "homedepot.com": {
        "price": ".price-format__main-price",
        "original_price": ".price-format__was-price",
        "in_stock": "#add-to-cart",
    },
    "wayfair.com": {
        "price": ".SFPrice--large, .BasePriceBlock",
        "original_price": ".SFPrice--strikethrough",
        "in_stock": ".AddToCartButton",
    },
    # ── Additional domains from 50-site integration test ─────────────
    "sephora.com": {
        "price": "[data-at='price'], .css-1jczs19, .css-0",
        "original_price": "[data-at='original_price'], .css-1qe8tjm",
        "in_stock": "[data-at='add_to_basket']",
    },
    "macys.com": {
        "price": ".lowest-sale-price, .regular-price, [data-auto='product-price']",
        "original_price": ".original-price, .regular-price",
        "in_stock": "[data-auto='add-to-bag']",
    },
    "bhphotovideo.com": {
        "price": "[data-selenium='pricingPrice'], .price_1DKkz",
        "original_price": "[data-selenium='pricingOriginalPrice']",
        "in_stock": "[data-selenium='addToCartButton']",
    },
    "adorama.com": {
        "price": ".product-price, .price-current",
        "original_price": ".price-was",
        "in_stock": ".add-to-cart",
    },
    "lowes.com": {
        "price": "[data-selector='splp-price'] span, .main-price",
        "original_price": ".was-price",
        "in_stock": "[data-selector='addToCart']",
    },
    "barnesandnoble.com": {
        "price": "#pdp-cur-price, .current-price",
        "original_price": "#pdp-old-price, .old-price",
        "in_stock": ".btn-add-to-cart",
    },
    "nordstrom.com": {
        "price": "[data-element='price'] span, .Rl5Qu",
        "original_price": "[data-element='original-price'] span",
        "in_stock": "[data-element='add-to-bag']",
    },
    "cb2.com": {
        "price": ".price-current, .priceView span",
        "original_price": ".price-was",
        "in_stock": ".add-to-cart-button",
    },
    "vitacost.com": {
        "price": ".product-price, .price",
        "original_price": ".product-price-was, .retail-price",
        "in_stock": ".add-to-cart",
    },
    "dickssportinggoods.com": {
        "price": ".product-price span, .price-was",
        "original_price": ".price-original",
        "in_stock": "[data-auid='addToBag']",
    },
    "rei.com": {
        "price": "#buy-box-product-price span, .price-value",
        "original_price": ".price-compare",
        "in_stock": "#add-to-cart",
    },
}

# ── Auto-discovery configuration ────────────────────────────────────────

# Regex matching price-related CSS classes / IDs
_PRICE_CLASS_RE = re.compile(
    r"price|cost|amount|sale-?price|our-?price|current-?price|"
    r"product-?price|final-?price|actual-?price|offer-?price|"
    r"price-?now|buy-?price|retail-?price",
    re.IGNORECASE,
)

# Regex matching product title/heading elements (for proximity scoring)
_PRODUCT_TITLE_RE = re.compile(
    r"product.?title|product.?name|pdp.?title|item.?title|"
    r"product.?heading|hero.?title",
    re.IGNORECASE,
)

# Price text pattern — must contain a currency symbol or number with decimals
_PRICE_TEXT_RE = re.compile(
    r"[$€£¥₹₽₩₪₺฿zł]\s*\d|\d+[.,]\d{2}",
)


class CSSSelectorStrategy(BaseStrategy):
    """Extract prices using domain-specific CSS selectors.

    Selectors can come from:
    1. DB-stored per-domain configs (passed in at init, hot-reloadable)
    2. Built-in DEFAULT_SELECTOR_CONFIGS for known platforms
    3. Per-CompetitorProduct selector_config overrides
    4. Auto-discovery (fallback when no config exists)
    """

    name = "css_selector"

    def __init__(
        self,
        db_configs: dict[str, dict[str, str]] | None = None,
        product_config: dict[str, Any] | None = None,
    ) -> None:
        self._db_configs = db_configs or {}
        self._product_config = product_config or {}

    def extract(self, soup: BeautifulSoup, url: str) -> PriceData | None:
        domain = self._extract_domain(url)
        config = self._resolve_config(domain)

        if config:
            return self._extract_with_config(soup, config)

        # No config → try auto-discovery
        return self._auto_discover(soup)

    # ── Config-based extraction ──────────────────────────────────────

    def _extract_with_config(
        self, soup: BeautifulSoup, config: dict[str, str]
    ) -> PriceData | None:
        """Extract using explicit CSS selectors from config."""
        # Extract current price
        price_raw = self._select_text(soup, config.get("price", ""))
        if not price_raw:
            return None

        current_price = parse_price(price_raw)
        if current_price is None or current_price <= 0:
            return None

        # Detect currency from the raw price text
        currency = detect_currency(price_raw)

        # Original / sale price
        original_raw = self._select_text(soup, config.get("original_price", ""))
        original_price = parse_price(original_raw) if original_raw else None

        # In-stock detection
        in_stock = self._detect_stock(soup, config.get("in_stock", ""))

        return PriceData(
            current_price=current_price,
            original_price=original_price,
            currency=normalize_currency_code(currency),
            in_stock=in_stock,
            strategy=self.name,
        )

    # ── Auto-discovery ───────────────────────────────────────────────

    def _auto_discover(self, soup: BeautifulSoup) -> PriceData | None:
        """Find price elements by scanning classes/ids for 'price' patterns.

        Scoring heuristic:
        1. Element class/id matches price regex → candidate
        2. Element text contains parseable price → +3 points
        3. Element is not hidden (no display:none / visibility:hidden) → +1
        4. Element is near a product-title element (shallow DOM) → +2
        5. Element text is short (< 30 chars, likely a price not a paragraph) → +1

        Returns the highest-scoring candidate.
        """
        candidates: list[tuple[float, Tag, str]] = []

        # Find all elements with price-like class or id
        for el in soup.find_all(True):
            if not isinstance(el, Tag):
                continue

            classes = " ".join(el.get("class", []))
            el_id = el.get("id", "") or ""
            combined = f"{classes} {el_id}"

            if not _PRICE_CLASS_RE.search(combined):
                continue

            text = el.get_text(strip=True)
            if not text:
                continue

            # Must look like a price
            if not _PRICE_TEXT_RE.search(text):
                continue

            price = parse_price(text)
            if price is None or price <= 0:
                continue

            # Score the candidate
            score = 3.0  # has parseable price

            # Shorter text is more likely a standalone price
            if len(text) < 30:
                score += 1.0

            # Check visibility (rough heuristic via style attribute)
            style = str(el.get("style", "")).lower()
            if "display:none" in style or "display: none" in style:
                continue  # skip hidden
            if "visibility:hidden" in style or "visibility: hidden" in style:
                continue
            score += 1.0  # visible

            # Proximity to product title
            if self._near_product_title(el):
                score += 2.0

            candidates.append((score, el, text))

        if not candidates:
            return None

        # Pick highest score
        candidates.sort(key=lambda x: x[0], reverse=True)
        _, best_el, best_text = candidates[0]

        price = parse_price(best_text)
        if price is None or price <= 0:
            return None

        currency = detect_currency(best_text)

        return PriceData(
            current_price=price,
            currency=normalize_currency_code(currency),
            strategy=self.name,
        )

    @staticmethod
    def _near_product_title(el: Tag) -> bool:
        """Check if element is near a product title in the DOM tree.

        Walks up to 5 levels up, then searches siblings/children for
        product-title indicators.
        """
        # Walk up the tree looking for a container that also has a title
        parent = el.parent
        for _ in range(5):
            if parent is None:
                break
            if isinstance(parent, Tag):
                # Check if parent contains a product title element
                for child in parent.find_all(True, recursive=True):
                    if not isinstance(child, Tag):
                        continue
                    classes = " ".join(child.get("class", []))
                    child_id = child.get("id", "") or ""
                    combined = f"{classes} {child_id}"
                    if _PRODUCT_TITLE_RE.search(combined):
                        return True
                    # Also check h1 tags as product titles
                    if child.name == "h1":
                        return True
            parent = parent.parent if parent else None
        return False

    # ── Stock detection ──────────────────────────────────────────────

    @staticmethod
    def _detect_stock(soup: BeautifulSoup, selector: str) -> bool:
        """Detect in-stock status from selector."""
        in_stock = True
        if not selector:
            return in_stock

        stock_el = soup.select_one(selector)
        if stock_el and isinstance(stock_el, Tag):
            text = stock_el.get_text(strip=True).lower()
            out_of_stock_terms = (
                "out of stock", "unavailable", "sold out",
                # Polish
                "niedostępny", "niedostepny", "brak w magazynie",
                # German
                "nicht verfügbar", "nicht verfugbar", "nicht auf lager",
                # French
                "indisponible", "rupture de stock",
                # Spanish
                "no disponible", "agotado",
            )
            if any(term in text for term in out_of_stock_terms):
                in_stock = False
        elif stock_el is None:
            # If the selector targets an "add to cart" button and it doesn't exist,
            # likely out of stock
            if "add" in selector.lower() or "cart" in selector.lower():
                in_stock = False

        return in_stock

    # ── Config resolution ────────────────────────────────────────────

    def _resolve_config(self, domain: str) -> dict[str, str] | None:
        """Resolve CSS selector config: product-level > DB > built-in defaults."""
        # 1. Product-level override
        if self._product_config:
            return {k: str(v) for k, v in self._product_config.items() if v}

        # 2. DB-stored domain config
        if domain in self._db_configs:
            return self._db_configs[domain]

        # 3. Built-in defaults — match against known domains
        for known_domain, config in DEFAULT_SELECTOR_CONFIGS.items():
            if known_domain in domain:
                return config

        # 4. Match by brand name for regional TLDs (e.g., amazon.pl -> amazon.com config)
        domain_brand = domain.split(".")[0]  # "amazon" from "amazon.pl"
        for known_domain, config in DEFAULT_SELECTOR_CONFIGS.items():
            known_brand = known_domain.split(".")[0]  # "amazon" from "amazon.com"
            if domain_brand == known_brand:
                return config

        return None

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract clean domain from URL."""
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path
        domain = domain.lower().replace("www.", "")
        return domain

    @staticmethod
    def _select_text(soup: BeautifulSoup, selector: str) -> str | None:
        """Get text content from first matching CSS selector."""
        if not selector:
            return None
        for sel in selector.split(","):
            sel = sel.strip()
            if not sel:
                continue
            el = soup.select_one(sel)
            if el and isinstance(el, Tag):
                text = el.get_text(strip=True)
                if text:
                    return text
        return None
