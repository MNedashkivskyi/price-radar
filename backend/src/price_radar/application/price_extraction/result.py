"""Data classes for price extraction results."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class PriceData:
    """Extracted price data from a single strategy."""

    current_price: Decimal | None = None
    original_price: Decimal | None = None
    sale_price: Decimal | None = None
    currency: str | None = None
    in_stock: bool | None = None
    strategy: str = ""

    @property
    def has_price(self) -> bool:
        return self.current_price is not None


@dataclass
class ExtractionResult:
    """Final extraction result with confidence scoring."""

    current_price: Decimal | None = None
    original_price: Decimal | None = None
    sale_price: Decimal | None = None
    currency: str = "USD"
    in_stock: bool = True
    confidence: float = 0.0
    strategies_used: list[str] = field(default_factory=list)
    all_results: list[PriceData] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.current_price is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "current_price": float(self.current_price) if self.current_price else None,
            "original_price": float(self.original_price) if self.original_price else None,
            "sale_price": float(self.sale_price) if self.sale_price else None,
            "currency": self.currency,
            "in_stock": self.in_stock,
            "confidence": round(self.confidence, 2),
            "strategies_used": self.strategies_used,
        }
