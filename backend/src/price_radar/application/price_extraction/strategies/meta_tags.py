"""Strategy: Twitter Card and custom meta tag price extraction.

Extracts prices from Twitter product cards and non-standard ``<meta>`` tags
that many e-commerce sites publish but are not covered by the Open Graph
strategy (which focuses on ``og:`` prefixed properties).

Targeted meta patterns:
- ``twitter:data1`` / ``twitter:label1`` (Twitter product card price)
- ``product:price:amount`` (with ``name`` attribute, not ``property``)
- ``price`` / ``product_price`` (generic meta names)
- ``amount`` (some Shopify themes)
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from price_radar.application.price_extraction.normalizer import (
    detect_currency,
    normalize_currency_code,
    parse_price,
)
from price_radar.application.price_extraction.result import PriceData
from price_radar.application.price_extraction.strategies.base import BaseStrategy

# Labels that indicate the twitter:data1 value is a price
_PRICE_LABELS = re.compile(
    r"price|cost|amount|msrp|retail|sale|buy",
    re.IGNORECASE,
)


class MetaTagStrategy(BaseStrategy):
    """Extract prices from Twitter Cards and custom meta tags."""

    name = "meta_tags"

    def extract(self, soup: BeautifulSoup, url: str) -> PriceData | None:
        # Try each method in priority order
        for method in (
            self._try_twitter_card,
            self._try_custom_meta_names,
            self._try_data_attributes,
        ):
            result = method(soup)
            if result is not None:
                return result
        return None

    # ── Twitter Card ─────────────────────────────────────────────────

    def _try_twitter_card(self, soup: BeautifulSoup) -> PriceData | None:
        """Extract from twitter:data1 / twitter:label1 product card tags.

        Example::

            <meta name="twitter:label1" content="Price">
            <meta name="twitter:data1" content="$29.99 USD">
        """
        # Find twitter:data* tags (data1, data2)
        for suffix in ("1", "2"):
            label_tag = soup.find(
                "meta", attrs={"name": f"twitter:label{suffix}"}
            )
            data_tag = soup.find(
                "meta", attrs={"name": f"twitter:data{suffix}"}
            )

            if not data_tag or not data_tag.get("content"):
                continue

            data_value = str(data_tag["content"]).strip()

            # Check if the label indicates price
            if label_tag and label_tag.get("content"):
                label = str(label_tag["content"]).strip()
                if not _PRICE_LABELS.search(label):
                    continue
            else:
                # No label — only accept if data looks like a price
                if not re.search(r"[$€£¥₹]\s*\d|^\d+[.,]\d{2}$", data_value):
                    continue

            price = parse_price(data_value)
            if price is None or price <= 0:
                continue

            currency = detect_currency(data_value)
            return PriceData(
                current_price=price,
                currency=normalize_currency_code(currency),
                strategy=self.name,
            )

        return None

    # ── Custom meta name tags ────────────────────────────────────────

    def _try_custom_meta_names(self, soup: BeautifulSoup) -> PriceData | None:
        """Extract from non-standard meta name tags.

        Example::

            <meta name="price" content="29.99">
            <meta name="product_price" content="$29.99">
            <meta name="product:price:amount" content="29.99">
            <meta name="amount" content="29.99">
        """
        price_meta_names = [
            "price",
            "product_price",
            "product:price:amount",
            "product:price",
            "amount",
            "Price",
            "priceCurrency",
        ]

        currency_meta_names = [
            "currency",
            "product:price:currency",
            "priceCurrency",
        ]

        price_value: str | None = None
        for name in price_meta_names:
            tag = soup.find("meta", attrs={"name": name})
            if tag and tag.get("content"):
                content = str(tag["content"]).strip()
                if content and re.search(r"\d", content):
                    price_value = content
                    break

        if not price_value:
            return None

        price = parse_price(price_value)
        if price is None or price <= 0:
            return None

        # Try to find currency
        currency = detect_currency(price_value)
        if not currency:
            for name in currency_meta_names:
                tag = soup.find("meta", attrs={"name": name})
                if tag and tag.get("content"):
                    currency = normalize_currency_code(str(tag["content"]).strip())
                    break

        # Availability from meta
        avail_tag = soup.find("meta", attrs={"name": "availability"})
        in_stock = None
        if avail_tag and avail_tag.get("content"):
            avail = str(avail_tag["content"]).strip().lower()
            in_stock = avail in ("instock", "in stock", "available", "true", "yes")

        return PriceData(
            current_price=price,
            currency=normalize_currency_code(currency),
            in_stock=in_stock,
            strategy=self.name,
        )

    # ── Data attributes on elements ──────────────────────────────────

    def _try_data_attributes(self, soup: BeautifulSoup) -> PriceData | None:
        """Extract from data-price / data-product-price attributes.

        Example::

            <div data-price="29.99" data-currency="USD">
            <span data-product-price="2999">
        """
        data_attrs = ["data-price", "data-product-price", "data-current-price"]

        for attr in data_attrs:
            elements = soup.find_all(attrs={attr: True})
            for el in elements:
                raw = str(el[attr]).strip()
                if not raw or not re.search(r"\d", raw):
                    continue

                price = parse_price(raw)
                if price is None or price <= 0:
                    continue

                # Heuristic: if price looks like cents (>= 100, no decimal), divide
                # e.g., data-product-price="2999" → $29.99
                if "." not in raw and "," not in raw and price >= 100:
                    from decimal import Decimal
                    cents_price = price / Decimal("100")
                    if cents_price >= 1:
                        price = cents_price

                currency = None
                for curr_attr in ("data-currency", "data-price-currency"):
                    if el.get(curr_attr):
                        currency = str(el[curr_attr]).strip()
                        break

                return PriceData(
                    current_price=price,
                    currency=normalize_currency_code(currency),
                    strategy=self.name,
                )

        return None
