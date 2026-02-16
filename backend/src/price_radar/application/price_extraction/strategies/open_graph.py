"""Strategy 2: Open Graph meta tags (og:price:amount, product:price:amount)."""

from __future__ import annotations

from bs4 import BeautifulSoup

from price_radar.application.price_extraction.normalizer import (
    normalize_currency_code,
    parse_price,
)
from price_radar.application.price_extraction.result import PriceData
from price_radar.application.price_extraction.strategies.base import BaseStrategy


class OpenGraphStrategy(BaseStrategy):
    """Extract prices from Open Graph and product meta tags."""

    name = "open_graph"

    def extract(self, soup: BeautifulSoup, url: str) -> PriceData | None:
        price = self._get_meta(soup, [
            "og:price:amount",
            "product:price:amount",
            "product:price",
            "price",
        ])
        if not price:
            return None

        current_price = parse_price(price)
        if current_price is None or current_price <= 0:
            return None

        # Currency
        currency_raw = self._get_meta(soup, [
            "og:price:currency",
            "product:price:currency",
            "currency",
        ])

        # Availability
        availability = self._get_meta(soup, [
            "og:availability",
            "product:availability",
            "availability",
        ])
        in_stock = self._parse_og_availability(availability)

        # Sale / original price from meta tags
        sale_raw = self._get_meta(soup, [
            "product:sale_price:amount",
            "og:price:sale_amount",
        ])
        original_raw = self._get_meta(soup, [
            "product:original_price:amount",
            "product:pretax_price:amount",
        ])

        sale_price = parse_price(sale_raw) if sale_raw else None
        original_price = parse_price(original_raw) if original_raw else None

        return PriceData(
            current_price=current_price,
            original_price=original_price,
            sale_price=sale_price,
            currency=normalize_currency_code(currency_raw),
            in_stock=in_stock,
            strategy=self.name,
        )

    @staticmethod
    def _get_meta(soup: BeautifulSoup, properties: list[str]) -> str | None:
        """Get content of first matching meta tag."""
        for prop in properties:
            tag = soup.find("meta", attrs={"property": prop})
            if tag and tag.get("content"):
                return str(tag["content"]).strip()
            # Some sites use name instead of property
            tag = soup.find("meta", attrs={"name": prop})
            if tag and tag.get("content"):
                return str(tag["content"]).strip()
        return None

    @staticmethod
    def _parse_og_availability(value: str | None) -> bool:
        """Parse OG availability value."""
        if not value:
            return True
        lower = value.lower().strip()
        return lower in ("instock", "in stock", "available", "true", "yes", "1")
