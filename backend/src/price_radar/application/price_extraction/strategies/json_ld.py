"""Strategy 1: JSON-LD structured data (schema.org/Product) — highest reliability."""

from __future__ import annotations

import json
import logging
from typing import Any

from bs4 import BeautifulSoup

from price_radar.application.price_extraction.normalizer import (
    normalize_currency_code,
    parse_price,
)
from price_radar.application.price_extraction.result import PriceData
from price_radar.application.price_extraction.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class JsonLdStrategy(BaseStrategy):
    """Extract prices from JSON-LD structured data (schema.org/Product)."""

    name = "json_ld"

    def extract(self, soup: BeautifulSoup, url: str) -> PriceData | None:
        scripts = soup.find_all("script", type="application/ld+json")
        for script in scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
            except (json.JSONDecodeError, TypeError):
                continue

            product = self._find_product(data)
            if product:
                return self._parse_product(product)

        return None

    def _find_product(self, data: Any) -> dict[str, Any] | None:
        """Recursively find a Product or schema.org/Product in JSON-LD data."""
        if isinstance(data, list):
            for item in data:
                result = self._find_product(item)
                if result:
                    return result
            return None

        if not isinstance(data, dict):
            return None

        # Check @type
        item_type = data.get("@type", "")
        if isinstance(item_type, list):
            types = item_type
        else:
            types = [item_type]

        for t in types:
            if t in ("Product", "http://schema.org/Product", "https://schema.org/Product"):
                return data

        # Check @graph
        if "@graph" in data:
            return self._find_product(data["@graph"])

        return None

    def _parse_product(self, product: dict[str, Any]) -> PriceData | None:
        """Parse price data from a schema.org Product object."""
        offers = product.get("offers")
        if not offers:
            return None

        # offers can be a single object or a list
        if isinstance(offers, list):
            offer = offers[0] if offers else None
        elif isinstance(offers, dict):
            # Could be an AggregateOffer with "offers" inside
            offer_type = offers.get("@type", "")
            if offer_type == "AggregateOffer":
                low_price = offers.get("lowPrice")
                currency = offers.get("priceCurrency")
                availability = offers.get("availability", "")
                in_stock = self._parse_availability(availability)
                price_val = parse_price(str(low_price)) if low_price else None
                if price_val is not None:
                    return PriceData(
                        current_price=price_val,
                        currency=normalize_currency_code(currency),
                        in_stock=in_stock,
                        strategy=self.name,
                    )
                # Fall through to nested offers
                nested = offers.get("offers")
                if isinstance(nested, list) and nested:
                    offer = nested[0]
                else:
                    offer = nested if isinstance(nested, dict) else None
            else:
                offer = offers
        else:
            return None

        if not offer or not isinstance(offer, dict):
            return None

        # Extract price
        price_raw = offer.get("price")
        if price_raw is None:
            price_raw = offer.get("priceSpecification", {}).get("price")

        current_price = parse_price(str(price_raw)) if price_raw is not None else None

        # Currency
        currency = offer.get("priceCurrency") or offer.get(
            "priceSpecification", {}
        ).get("priceCurrency")

        # Availability
        availability = offer.get("availability", "")
        in_stock = self._parse_availability(availability)

        if current_price is None:
            return None

        return PriceData(
            current_price=current_price,
            currency=normalize_currency_code(currency),
            in_stock=in_stock,
            strategy=self.name,
        )

    @staticmethod
    def _parse_availability(availability: str) -> bool:
        """Parse schema.org availability value."""
        if not availability:
            return True
        availability_lower = availability.lower()
        out_of_stock_terms = [
            "outofstock",
            "discontinued",
            "soldout",
            "preorder",
        ]
        return not any(term in availability_lower for term in out_of_stock_terms)
