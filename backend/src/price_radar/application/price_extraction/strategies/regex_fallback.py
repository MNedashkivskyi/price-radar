"""Strategy 5: Regex fallback patterns for common price formats."""

from __future__ import annotations

import re
from decimal import Decimal

from bs4 import BeautifulSoup

from price_radar.application.price_extraction.normalizer import (
    detect_currency,
    normalize_currency_code,
    parse_price,
)
from price_radar.application.price_extraction.result import PriceData
from price_radar.application.price_extraction.strategies.base import BaseStrategy

# ── Sanity bounds ────────────────────────────────────────────────────────
# Regex is the lowest-confidence strategy.  Reject prices that are
# implausibly high — they almost always come from matching product IDs,
# page numbers, or other large numbers that happen to look like prices.
_MAX_SANE_PRICE = Decimal("50000")
_MIN_SANE_PRICE = Decimal("0.01")

# Patterns ordered by specificity (most specific first)
PRICE_PATTERNS: list[re.Pattern[str]] = [
    # "$1,234.56" or "€1.234,56" with currency symbol (prefix)
    re.compile(
        r"(?:[\$\u20ac\u00a3\u00a5\u20b9\u20bd\u20a9\u20ba\u20b1\u20aa\u0e3f\u20ab])"
        r"\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)"
    ),
    # "1.234,56 zł" or "123,45 zł" with Polish złoty suffix
    re.compile(
        r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)"
        r"\s*z[ł\u0142l]"
    ),
    # "1,234.56 USD" or "1.234,56 EUR" with currency code after
    re.compile(
        r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)"
        r"\s*([A-Z]{3})\b"
    ),
    # Price with currency prefix like "USD 29.99"
    re.compile(
        r"\b([A-Z]{3})\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)"
    ),
    # Generic price-like number near price-related class/text
    re.compile(
        r"(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})"
    ),
]


class RegexFallbackStrategy(BaseStrategy):
    """Last-resort regex-based price extraction from page text."""

    name = "regex_fallback"

    def extract(self, soup: BeautifulSoup, url: str) -> PriceData | None:
        # First, try to find price in elements with price-related classes/ids
        price_data = self._extract_from_price_elements(soup)
        if price_data:
            return price_data

        # Fall back to scanning visible text
        return self._extract_from_text(soup)

    def _extract_from_price_elements(self, soup: BeautifulSoup) -> PriceData | None:
        """Search for prices in elements that have price-related CSS classes or IDs."""
        price_indicators = re.compile(
            r"price|cost|amount|sale|offer|discount", re.IGNORECASE
        )

        candidates: list[tuple[str, str]] = []

        for el in soup.find_all(attrs={"class": price_indicators}):
            text = el.get_text(strip=True)
            if text and len(text) < 50:
                candidates.append(("class", text))

        for el in soup.find_all(attrs={"id": price_indicators}):
            text = el.get_text(strip=True)
            if text and len(text) < 50:
                candidates.append(("id", text))

        # Also check data-price attributes
        for el in soup.find_all(attrs={"data-price": True}):
            val = el.get("data-price", "")
            if val:
                candidates.append(("data-price", str(val)))

        if not candidates:
            return None

        # Try to parse the first valid price from candidates
        for _source, text in candidates:
            for pattern in PRICE_PATTERNS:
                match = pattern.search(text)
                if match:
                    # Reconstruct the full price string for parsing
                    full_match = match.group(0)
                    price_val = parse_price(full_match)
                    if (
                        price_val is not None
                        and _MIN_SANE_PRICE <= price_val <= _MAX_SANE_PRICE
                    ):
                        currency = detect_currency(text)
                        return PriceData(
                            current_price=price_val,
                            currency=normalize_currency_code(currency),
                            strategy=self.name,
                        )

        return None

    def _extract_from_text(self, soup: BeautifulSoup) -> PriceData | None:
        """Scan visible page text for price patterns."""
        # Get body text, falling back to full page
        body = soup.find("body")
        if not body:
            return None

        text = body.get_text(" ", strip=True)
        if not text:
            return None

        # Limit search to first 5000 chars to avoid scanning entire page text
        text = text[:5000]

        for pattern in PRICE_PATTERNS:
            match = pattern.search(text)
            if match:
                full_match = match.group(0)
                price_val = parse_price(full_match)
                if (
                    price_val is not None
                    and _MIN_SANE_PRICE <= price_val <= _MAX_SANE_PRICE
                ):
                    currency = detect_currency(full_match)
                    return PriceData(
                        current_price=price_val,
                        currency=normalize_currency_code(currency),
                        strategy=self.name,
                    )

        return None
