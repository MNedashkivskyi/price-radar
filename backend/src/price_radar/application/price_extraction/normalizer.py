"""Price normalization: currency detection, decimal handling, sale vs regular price."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# Currency symbol to ISO code mapping
CURRENCY_SYMBOLS: dict[str, str] = {
    "$": "USD",
    "\u20ac": "EUR",
    "\u00a3": "GBP",
    "\u00a5": "JPY",
    "\u20b9": "INR",
    "\u20bd": "RUB",
    "R$": "BRL",
    "C$": "CAD",
    "A$": "AUD",
    "NZ$": "NZD",
    "HK$": "HKD",
    "S$": "SGD",
    "\u20a9": "KRW",
    "z\u0142": "PLN",
    "kr": "SEK",  # Also NOK, DKK — context-dependent
    "CHF": "CHF",
    "\u20ba": "TRY",
    "R": "ZAR",
    "\u20b1": "PHP",
    "\u20aa": "ILS",
    "\u0e3f": "THB",
    "RM": "MYR",
    "Rp": "IDR",
    "\u20ab": "VND",
}

# ISO currency codes (3-letter uppercase)
VALID_CURRENCY_CODES: set[str] = {
    "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "INR", "BRL",
    "RUB", "KRW", "SGD", "HKD", "NOK", "SEK", "DKK", "NZD", "ZAR", "MXN",
    "TRY", "PLN", "THB", "IDR", "MYR", "PHP", "ILS", "CZK", "CLP", "ARS",
    "COP", "PEN", "UAH", "RON", "HUF", "VND", "TWD", "AED", "SAR", "QAR",
    "KWD", "BHD", "OMR", "JOD", "EGP", "NGN", "KES", "GHS", "TZS",
}

# Zero-decimal currencies (no cents)
ZERO_DECIMAL_CURRENCIES: set[str] = {
    "JPY", "KRW", "VND", "IDR", "CLP", "HUF",
}


def detect_currency(text: str) -> str | None:
    """Detect currency from text containing price with currency symbol or code."""
    text = text.strip()

    # Check for multi-char symbols first (R$, C$, etc.)
    for symbol, code in sorted(CURRENCY_SYMBOLS.items(), key=lambda x: -len(x[0])):
        if symbol in text:
            return code

    # Check for ISO code in text
    iso_match = re.search(r"\b([A-Z]{3})\b", text)
    if iso_match and iso_match.group(1) in VALID_CURRENCY_CODES:
        return iso_match.group(1)

    return None


def parse_price(raw: str) -> Decimal | None:
    """Parse a price string into a Decimal, handling international formats.

    Supports formats like:
      $1,234.56  |  1.234,56 €  |  1 234,56  |  ¥1234  |  $29.99
    """
    if not raw or not raw.strip():
        return None

    # Remove currency symbols and whitespace
    cleaned = raw.strip()
    for symbol in CURRENCY_SYMBOLS:
        cleaned = cleaned.replace(symbol, "")
    # Remove ISO currency codes
    cleaned = re.sub(r"\b[A-Z]{3}\b", "", cleaned)
    cleaned = cleaned.strip()

    # Remove all whitespace (including non-breaking spaces used as thousands sep)
    cleaned = re.sub(r"\s+", "", cleaned)

    if not cleaned:
        return None

    # Extract numeric portion (digits, dots, commas, minus)
    numeric_match = re.search(r"-?[\d.,]+", cleaned)
    if not numeric_match:
        return None

    num_str = numeric_match.group()

    # Determine format based on separator patterns
    dots = num_str.count(".")
    commas = num_str.count(",")

    if dots == 0 and commas == 0:
        # Plain integer: "1234"
        pass
    elif dots == 1 and commas == 0:
        # Could be "1234.56" (decimal) or "1.234" (thousands)
        # If exactly 3 digits after dot and no other context, treat as decimal
        # unless it looks like a thousands separator
        after_dot = num_str.split(".")[1]
        if len(after_dot) == 3 and len(num_str.split(".")[0]) <= 3:
            # Ambiguous like "1.234" — could be 1234 or 1.234
            # Default to decimal interpretation (US/UK style)
            pass
        # Standard decimal: keep as-is
    elif dots == 0 and commas == 1:
        # Could be "1,234" (thousands) or "12,50" (European decimal)
        after_comma = num_str.split(",")[1]
        if len(after_comma) <= 2:
            # European decimal: "12,50" -> "12.50"
            num_str = num_str.replace(",", ".")
        else:
            # Thousands separator: "1,234" -> "1234"
            num_str = num_str.replace(",", "")
    elif dots >= 1 and commas >= 1:
        # Mixed separators — figure out which is the decimal
        last_dot = num_str.rfind(".")
        last_comma = num_str.rfind(",")
        if last_dot > last_comma:
            # Format: "1,234.56" — comma is thousands, dot is decimal
            num_str = num_str.replace(",", "")
        else:
            # Format: "1.234,56" — dot is thousands, comma is decimal
            num_str = num_str.replace(".", "").replace(",", ".")
    elif commas > 1:
        # Multiple commas, no dots: "1,234,567" — all thousands
        num_str = num_str.replace(",", "")
    elif dots > 1:
        # Multiple dots, no commas: "1.234.567" — all thousands
        num_str = num_str.replace(".", "")

    try:
        value = Decimal(num_str)
        if value < 0:
            return None
        return value
    except InvalidOperation:
        return None


def normalize_currency_code(raw: str | None) -> str:
    """Normalize a raw currency string to an ISO 4217 code."""
    if not raw:
        return "USD"

    raw = raw.strip().upper()
    if raw in VALID_CURRENCY_CODES:
        return raw

    # Try to detect from symbol
    detected = detect_currency(raw)
    return detected or "USD"
