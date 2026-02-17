"""Generic price extractor orchestrator with multi-strategy fallback and confidence scoring."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from bs4 import BeautifulSoup

from price_radar.application.price_extraction.result import ExtractionResult, PriceData
from price_radar.application.price_extraction.strategies.base import BaseStrategy
from price_radar.application.price_extraction.strategies.css_selector import CSSSelectorStrategy
from price_radar.application.price_extraction.strategies.json_ld import JsonLdStrategy
from price_radar.application.price_extraction.strategies.meta_tags import MetaTagStrategy
from price_radar.application.price_extraction.strategies.microdata import MicrodataStrategy
from price_radar.application.price_extraction.strategies.open_graph import OpenGraphStrategy
from price_radar.application.price_extraction.strategies.regex_fallback import (
    RegexFallbackStrategy,
)
from price_radar.application.price_extraction.strategies.script_tag import ScriptTagStrategy
from price_radar.application.price_extraction.strategies.shopify_api import ShopifyApiStrategy

logger = logging.getLogger(__name__)

# Strategy reliability weights (used in confidence scoring)
STRATEGY_WEIGHTS: dict[str, float] = {
    "json_ld": 1.0,
    "shopify_api": 0.95,
    "script_tag": 0.92,
    "open_graph": 0.85,
    "meta_tags": 0.82,
    "microdata": 0.80,
    "css_selector": 0.70,
    "regex_fallback": 0.40,
}


class PriceExtractor:
    """Orchestrates multiple price extraction strategies with confidence scoring.

    Strategies are executed in priority order:
    1. JSON-LD (schema.org/Product) — highest reliability
    2. Shopify JSON API (/products/{handle}.json) — Shopify stores only
    3. Script tag data (__NEXT_DATA__, __INITIAL_STATE__) — SPA frameworks
    4. Open Graph meta tags
    5. Microdata (itemprop)
    6. CSS selectors (domain-specific, DB-configurable)
    7. Regex fallback

    When multiple strategies agree on the price, confidence is higher.
    """

    def __init__(
        self,
        db_selector_configs: dict[str, dict[str, str]] | None = None,
        product_selector_config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize with optional domain-specific selector configs.

        Args:
            db_selector_configs: Per-domain CSS selector configs from DB.
            product_selector_config: Per-product CSS selector override.
        """
        self._strategies: list[BaseStrategy] = [
            JsonLdStrategy(),
            ShopifyApiStrategy(),
            ScriptTagStrategy(),
            OpenGraphStrategy(),
            MetaTagStrategy(),
            MicrodataStrategy(),
            CSSSelectorStrategy(
                db_configs=db_selector_configs,
                product_config=product_selector_config,
            ),
            RegexFallbackStrategy(),
        ]

    def extract(self, html: str, url: str) -> ExtractionResult:
        """Extract price from HTML using all strategies, then score confidence.

        Args:
            html: Raw HTML content of the product page.
            url: The page URL.

        Returns:
            ExtractionResult with best price, confidence score, and metadata.
        """
        soup = BeautifulSoup(html, "html.parser")
        results: list[PriceData] = []

        for strategy in self._strategies:
            try:
                result = strategy.extract(soup, url)
                if result and result.has_price:
                    results.append(result)
                    logger.debug(
                        "Strategy %s extracted price: %s %s",
                        strategy.name,
                        result.current_price,
                        result.currency,
                    )
            except Exception:
                logger.exception("Strategy %s failed for %s", strategy.name, url)

        if not results:
            return ExtractionResult(confidence=0.0, all_results=[])

        return self._build_result(results)

    def _build_result(self, results: list[PriceData]) -> ExtractionResult:
        """Build final result with confidence scoring from multiple strategy results."""
        # Find the best price using weighted voting
        best = self._select_best_price(results)

        # Calculate confidence
        confidence = self._calculate_confidence(results, best)

        # Merge additional data (original_price, sale_price) from all results
        original_price = best.original_price
        sale_price = best.sale_price
        in_stock = best.in_stock

        for r in results:
            if r.original_price and not original_price:
                original_price = r.original_price
            if r.sale_price and not sale_price:
                sale_price = r.sale_price
            if r.in_stock is not None and in_stock is None:
                in_stock = r.in_stock

        # If original_price > current_price, current is the sale price
        if (
            original_price
            and best.current_price
            and original_price > best.current_price
            and not sale_price
        ):
            sale_price = best.current_price

        strategies_used = [r.strategy for r in results]

        return ExtractionResult(
            current_price=best.current_price,
            original_price=original_price,
            sale_price=sale_price,
            currency=best.currency or "USD",
            in_stock=in_stock if in_stock is not None else True,
            confidence=confidence,
            strategies_used=strategies_used,
            all_results=results,
        )

    @staticmethod
    def _select_best_price(results: list[PriceData]) -> PriceData:
        """Select the best price using strategy weight and agreement."""
        if len(results) == 1:
            return results[0]

        # Group results by price value (rounded to 2 decimal places)
        price_groups: dict[Decimal, list[PriceData]] = {}
        for r in results:
            if r.current_price is not None:
                key = round(r.current_price, 2)
                price_groups.setdefault(key, []).append(r)

        # Find the price value with the highest combined weight
        best_price: Decimal | None = None
        best_weight = -1.0

        for price_val, group in price_groups.items():
            total_weight = sum(
                STRATEGY_WEIGHTS.get(r.strategy, 0.5) for r in group
            )
            # Bonus for agreement between multiple strategies
            if len(group) > 1:
                total_weight *= 1.0 + 0.2 * (len(group) - 1)

            if total_weight > best_weight:
                best_weight = total_weight
                best_price = price_val

        # Return the highest-weighted individual result at that price
        if best_price is not None:
            candidates = price_groups[best_price]
            candidates.sort(
                key=lambda r: STRATEGY_WEIGHTS.get(r.strategy, 0.5),
                reverse=True,
            )
            return candidates[0]

        # Fallback: return highest-weighted result overall (without mutating input)
        sorted_results = sorted(
            results,
            key=lambda r: STRATEGY_WEIGHTS.get(r.strategy, 0.5),
            reverse=True,
        )
        return sorted_results[0]

    @staticmethod
    def _calculate_confidence(results: list[PriceData], best: PriceData) -> float:
        """Calculate confidence score (0.0–1.0) based on strategy agreement.

        Factors:
        - Base weight of the best strategy
        - Agreement: how many strategies found the same price
        - Completeness: whether currency, in_stock, etc. were extracted
        """
        if not best.current_price:
            return 0.0

        base_weight = STRATEGY_WEIGHTS.get(best.strategy, 0.5)
        best_rounded = round(best.current_price, 2)

        # Count how many strategies agree
        agreeing = sum(
            1
            for r in results
            if r.current_price is not None and round(r.current_price, 2) == best_rounded
        )
        total = len(results)

        # Agreement bonus: 0–0.3 based on fraction of strategies that agree
        if total > 1:
            agreement_bonus = 0.3 * (agreeing - 1) / (total - 1) if total > 1 else 0.0
        else:
            agreement_bonus = 0.0

        # Completeness bonus: up to 0.1
        completeness = 0.0
        # Check if any result found an explicit currency
        has_currency = any(r.currency for r in results if r.currency)
        if has_currency:
            completeness += 0.05
        # Check if any result found in_stock status
        if any(r.in_stock is not None for r in results):
            completeness += 0.05

        confidence = min(base_weight + agreement_bonus + completeness, 1.0)
        return round(confidence, 2)
