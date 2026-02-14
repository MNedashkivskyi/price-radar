"""Base class for price extraction strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod

from bs4 import BeautifulSoup

from price_radar.application.price_extraction.result import PriceData


class BaseStrategy(ABC):
    """Abstract base class for all extraction strategies."""

    name: str = "base"

    @abstractmethod
    def extract(self, soup: BeautifulSoup, url: str) -> PriceData | None:
        """Extract price data from parsed HTML.

        Args:
            soup: Parsed HTML document.
            url: The page URL (for domain-specific logic).

        Returns:
            PriceData if extraction succeeded, None otherwise.
        """
