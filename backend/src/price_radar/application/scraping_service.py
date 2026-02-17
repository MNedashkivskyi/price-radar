"""Scraping service — orchestrates price extraction for competitor products.

This is the core business logic layer between the Celery tasks and the
price extraction engine.  It:

1. Fetches a competitor product page (httpx → Camoufox fallback)
2. Extracts the price using the 7-strategy extractor
3. Deduplicates: skips insert when price/currency/in_stock unchanged
4. Stores a ``PricePoint`` row on change
5. Updates ``CompetitorProduct`` bookkeeping (last_price, fetch_strategy, etc.)
6. Marks products as ``"failed"`` after ``MAX_CONSECUTIVE_FAILURES`` failures

Usage::

    from price_radar.application.scraping_service import ScrapingService

    service = ScrapingService(db_session)
    result = await service.scrape_one(competitor_product_id=42)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import desc, select

from price_radar.application.price_extraction.fetcher import FetchResult, PageFetcher
from price_radar.application.price_extraction.result import ExtractionResult

from price_radar.infrastructure.models import CompetitorProduct, PricePoint

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Number of consecutive failures before marking a CompetitorProduct as "failed"
MAX_CONSECUTIVE_FAILURES = 5


@dataclass
class ScrapeResult:
    """Outcome of a single scrape attempt."""

    competitor_product_id: int
    success: bool
    price: Decimal | None = None
    currency: str | None = None
    in_stock: bool | None = None
    fetch_method: str = "none"
    was_deduplicated: bool = False  # True when price unchanged → no new PricePoint
    error: str | None = None
    fetch_time: float = 0.0
    confidence: float = 0.0
    strategies_used: list[str] | None = None


class ScrapingService:
    """Orchestrates scraping a single ``CompetitorProduct`` URL.

    Designed to be called from a Celery task that passes in a DB session
    and calls :meth:`scrape_one` with the competitor product ID.

    Args:
        db: Async SQLAlchemy session (provided by Celery task wrapper).
        fetcher: Optional ``PageFetcher`` instance (reused across calls
            within the same worker to keep the Camoufox browser alive).
    """

    def __init__(
        self,
        db: AsyncSession,
        fetcher: PageFetcher | None = None,
    ) -> None:
        self._db = db
        self._fetcher = fetcher or PageFetcher(use_browser=True)

    # ── Public API ───────────────────────────────────────────────────

    async def scrape_one(self, competitor_product_id: int) -> ScrapeResult:
        """Scrape a single competitor product and store the result.

        Steps:
            1. Load the ``CompetitorProduct`` row.
            2. Fetch + extract the price (sync call delegated to PageFetcher).
            3. Deduplicate against the latest ``PricePoint``.
            4. On price change → insert new ``PricePoint``.
            5. Update ``CompetitorProduct`` bookkeeping.
            6. On failure → increment ``consecutive_failures``, mark failed after 5.

        Returns:
            ``ScrapeResult`` with the outcome.
        """
        # 1. Load competitor product
        cp = await self._load_competitor_product(competitor_product_id)
        if cp is None:
            return ScrapeResult(
                competitor_product_id=competitor_product_id,
                success=False,
                error="competitor_product_not_found",
            )

        if cp.status == "paused":
            return ScrapeResult(
                competitor_product_id=competitor_product_id,
                success=False,
                error="competitor_product_paused",
            )

        now = datetime.now(timezone.utc)

        # 2. Fetch + extract (synchronous — PageFetcher uses sync httpx/Camoufox)
        try:
            fetch_result, extraction = self._fetcher.fetch_and_extract(cp.url)
        except Exception as e:
            logger.exception("Unexpected error scraping cp=%d url=%s", cp.id, cp.url)
            await self._record_failure(cp, now, error=str(e))
            return ScrapeResult(
                competitor_product_id=cp.id,
                success=False,
                error=f"unexpected_error: {type(e).__name__}: {e}",
            )

        # 3. Handle fetch/extraction failure
        if not fetch_result.success or not extraction.success:
            error = fetch_result.error or "extraction_failed"
            await self._record_failure(cp, now, error=error)
            return ScrapeResult(
                competitor_product_id=cp.id,
                success=False,
                error=error,
                fetch_method=fetch_result.method,
                fetch_time=fetch_result.fetch_time,
            )

        # 4. Extraction succeeded — check for dedup
        price = extraction.current_price
        currency = extraction.currency
        in_stock = extraction.in_stock

        latest_pp = await self._get_latest_price_point(cp.id)
        deduplicated = self._is_duplicate(latest_pp, price, currency, in_stock)

        if not deduplicated:
            # Insert new PricePoint
            pp = PricePoint(
                competitor_product_id=cp.id,
                price=float(price) if price else 0.0,
                original_price=(
                    float(extraction.original_price) if extraction.original_price else None
                ),
                sale_price=(
                    float(extraction.sale_price) if extraction.sale_price else None
                ),
                currency=currency,
                in_stock=in_stock,
                scraped_at=now,
            )
            self._db.add(pp)

        # 5. Update CompetitorProduct bookkeeping
        await self._record_success(
            cp,
            now,
            price=price,
            fetch_method=fetch_result.method,
        )

        await self._db.commit()

        return ScrapeResult(
            competitor_product_id=cp.id,
            success=True,
            price=price,
            currency=currency,
            in_stock=in_stock,
            fetch_method=fetch_result.method,
            was_deduplicated=deduplicated,
            fetch_time=fetch_result.fetch_time,
            confidence=extraction.confidence,
            strategies_used=extraction.strategies_used,
        )

    # ── Internal helpers ─────────────────────────────────────────────

    async def _load_competitor_product(
        self, competitor_product_id: int
    ) -> CompetitorProduct | None:
        """Load a CompetitorProduct by ID."""
        result = await self._db.execute(
            select(CompetitorProduct).where(
                CompetitorProduct.id == competitor_product_id
            )
        )
        return result.scalar_one_or_none()

    async def _get_latest_price_point(
        self, competitor_product_id: int
    ) -> PricePoint | None:
        """Get the most recent PricePoint for a competitor product."""
        result = await self._db.execute(
            select(PricePoint)
            .where(PricePoint.competitor_product_id == competitor_product_id)
            .order_by(desc(PricePoint.scraped_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _is_duplicate(
        latest: PricePoint | None,
        price: Decimal | None,
        currency: str,
        in_stock: bool,
    ) -> bool:
        """Return True if the new data is identical to the latest PricePoint."""
        if latest is None or price is None:
            return False

        # Compare price (Decimal vs Numeric — convert both to float for safe cmp)
        try:
            latest_price = float(latest.price)
            new_price = float(price)
        except (TypeError, ValueError):
            return False

        return (
            abs(latest_price - new_price) < 0.005  # within half a cent
            and latest.currency == currency
            and latest.in_stock == in_stock
        )

    async def _record_success(
        self,
        cp: CompetitorProduct,
        now: datetime,
        *,
        price: Decimal | None,
        fetch_method: str,
    ) -> None:
        """Update CompetitorProduct after a successful scrape."""
        cp.last_scraped_at = now
        cp.last_success_at = now
        cp.consecutive_failures = 0
        cp.fetch_strategy = fetch_method
        if price is not None:
            cp.last_price = float(price)
        if cp.status == "failed":
            cp.status = "active"  # Auto-recover from failed state
        self._db.add(cp)

    async def _record_failure(
        self,
        cp: CompetitorProduct,
        now: datetime,
        *,
        error: str,
    ) -> None:
        """Update CompetitorProduct after a failed scrape."""
        cp.last_scraped_at = now
        cp.consecutive_failures = (cp.consecutive_failures or 0) + 1

        if cp.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            cp.status = "failed"
            logger.warning(
                "CompetitorProduct %d marked as failed after %d consecutive failures: %s",
                cp.id,
                cp.consecutive_failures,
                error,
            )

        self._db.add(cp)
        await self._db.commit()
