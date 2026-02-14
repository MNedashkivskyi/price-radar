"""Strategy 3: Microdata (itemprop='price') extraction."""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from price_radar.application.price_extraction.normalizer import (
    normalize_currency_code,
    parse_price,
)
from price_radar.application.price_extraction.result import PriceData
from price_radar.application.price_extraction.strategies.base import BaseStrategy


class MicrodataStrategy(BaseStrategy):
    """Extract prices from HTML5 microdata attributes (itemprop)."""

    name = "microdata"

    def extract(self, soup: BeautifulSoup, url: str) -> PriceData | None:
        # Find elements with itemprop="price"
        price_el = soup.find(attrs={"itemprop": "price"})
        if not price_el or not isinstance(price_el, Tag):
            return None

        # Price value can be in content attr, value attr, or text
        price_raw = (
            price_el.get("content")
            or price_el.get("value")
            or price_el.get_text(strip=True)
        )
        if not price_raw:
            return None

        current_price = parse_price(str(price_raw))
        if current_price is None:
            return None

        # Currency from itemprop="priceCurrency"
        currency_el = soup.find(attrs={"itemprop": "priceCurrency"})
        currency_raw = None
        if currency_el and isinstance(currency_el, Tag):
            currency_raw = str(
                currency_el.get("content")
                or currency_el.get("value")
                or currency_el.get_text(strip=True)
            )

        # Availability from itemprop="availability"
        avail_el = soup.find(attrs={"itemprop": "availability"})
        in_stock = True
        if avail_el and isinstance(avail_el, Tag):
            avail_val = str(
                avail_el.get("href")
                or avail_el.get("content")
                or avail_el.get_text(strip=True)
            )
            in_stock = self._parse_microdata_availability(avail_val)

        return PriceData(
            current_price=current_price,
            currency=normalize_currency_code(currency_raw),
            in_stock=in_stock,
            strategy=self.name,
        )

    @staticmethod
    def _parse_microdata_availability(value: str) -> bool:
        """Parse microdata availability (often a schema.org URL)."""
        lower = value.lower()
        out_of_stock_terms = ["outofstock", "discontinued", "soldout"]
        return not any(term in lower for term in out_of_stock_terms)
