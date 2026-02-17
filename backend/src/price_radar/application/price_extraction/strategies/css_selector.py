"""Strategy 4: CSS selector configs per domain (stored in DB, hot-reloadable)."""

from __future__ import annotations

import logging
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
}


class CSSSelectorStrategy(BaseStrategy):
    """Extract prices using domain-specific CSS selectors.

    Selectors can come from:
    1. DB-stored per-domain configs (passed in at init, hot-reloadable)
    2. Built-in DEFAULT_SELECTOR_CONFIGS for known platforms
    3. Per-CompetitorProduct selector_config overrides
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
        if not config:
            return None

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
        in_stock = True
        in_stock_selector = config.get("in_stock", "")
        if in_stock_selector:
            stock_el = soup.select_one(in_stock_selector)
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
                if "add" in in_stock_selector.lower() or "cart" in in_stock_selector.lower():
                    in_stock = False

        return PriceData(
            current_price=current_price,
            original_price=original_price,
            currency=normalize_currency_code(currency),
            in_stock=in_stock,
            strategy=self.name,
        )

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
