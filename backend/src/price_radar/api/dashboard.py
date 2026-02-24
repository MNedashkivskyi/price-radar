"""Dashboard API endpoints."""

import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, literal_column, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from price_radar.api.middleware import get_current_shop_id
from price_radar.api.schemas import (
    AttentionProduct,
    DashboardOverviewResponse,
    DashboardSummary,
    PricePositionDistribution,
)
from price_radar.infrastructure.database import get_db
from price_radar.infrastructure.models import (
    Competitor,
    CompetitorProduct,
    PricePoint,
    Product,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview", response_model=DashboardOverviewResponse)
async def get_dashboard_overview(
    shop_id: int = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return all data needed for the main dashboard in a single request.

    Includes:
    - Summary stats (products tracked, competitors, price changes 24h, scraping health)
    - Price position distribution (cheapest, within 5%, above average, most expensive)
    - Products needing attention (competitors undercutting our price)

    All queries are scoped to the authenticated shop.
    """
    now = datetime.utcnow()
    twenty_four_hours_ago = now - timedelta(hours=24)

    # ── 1. Summary stats ───────────────────────────────────────────────────

    # a) Products tracked
    products_tracked_result = await db.execute(
        select(func.count(Product.id)).where(
            Product.shop_id == shop_id,
            Product.status == "active",
        )
    )
    products_tracked = products_tracked_result.scalar() or 0

    # b) Competitors monitored
    competitors_result = await db.execute(
        select(func.count(Competitor.id)).where(
            Competitor.shop_id == shop_id,
            Competitor.status == "active",
        )
    )
    competitors_monitored = competitors_result.scalar() or 0

    # c) Price changes in last 24 hours
    #    Count price_points where the price differs from the previous one
    #    for the same competitor_product, scraped in the last 24h.
    #    We use a window function to compare each price to the previous one.
    price_changes_result = await db.execute(
        text("""
            WITH recent_points AS (
                SELECT
                    pp.id,
                    pp.competitor_product_id,
                    pp.price,
                    pp.scraped_at,
                    LAG(pp.price) OVER (
                        PARTITION BY pp.competitor_product_id
                        ORDER BY pp.scraped_at
                    ) AS prev_price
                FROM price_points pp
                JOIN competitor_products cp ON pp.competitor_product_id = cp.id
                JOIN products p ON cp.product_id = p.id
                WHERE p.shop_id = :shop_id
                  AND pp.scraped_at >= :since
            )
            SELECT COUNT(*)
            FROM recent_points
            WHERE prev_price IS NOT NULL
              AND price != prev_price
        """),
        {"shop_id": shop_id, "since": twenty_four_hours_ago},
    )
    price_changes_24h = price_changes_result.scalar() or 0

    # d) Scraping health percentage
    #    Of all non-paused competitor_products for this shop,
    #    what % had a successful scrape in the last 24h?
    health_result = await db.execute(
        select(
            func.count(CompetitorProduct.id).filter(
                CompetitorProduct.status == "active",
                CompetitorProduct.last_success_at >= twenty_four_hours_ago,
            )
            * literal_column("100.0")
            / func.nullif(func.count(CompetitorProduct.id), 0)
        )
        .select_from(CompetitorProduct)
        .join(Product, CompetitorProduct.product_id == Product.id)
        .where(
            Product.shop_id == shop_id,
            CompetitorProduct.status != "paused",
        )
    )
    scraping_health_pct = round(float(health_result.scalar() or 0), 1)

    summary = DashboardSummary(
        products_tracked=products_tracked,
        products_trend_pct=0.0,  # Trend computation deferred for now
        competitors_monitored=competitors_monitored,
        price_changes_24h=price_changes_24h,
        scraping_health_pct=scraping_health_pct,
    )

    # ── 2. Price position distribution ─────────────────────────────────────
    #    For each active product, compare our_price vs competitor prices.

    product_positions = (
        select(
            Product.id,
            Product.our_price,
            func.min(CompetitorProduct.last_price).label("cheapest_competitor"),
            func.avg(CompetitorProduct.last_price).label("avg_competitor"),
        )
        .join(
            CompetitorProduct,
            (CompetitorProduct.product_id == Product.id)
            & (CompetitorProduct.status == "active"),
        )
        .where(
            Product.shop_id == shop_id,
            Product.status == "active",
            CompetitorProduct.last_price.isnot(None),
        )
        .group_by(Product.id, Product.our_price)
        .subquery()
    )

    pp = product_positions.c

    distribution_result = await db.execute(
        select(
            func.count()
            .filter(pp.our_price <= pp.cheapest_competitor)
            .label("cheapest"),
            func.count()
            .filter(
                pp.our_price > pp.cheapest_competitor,
                pp.our_price <= pp.avg_competitor * 1.05,
            )
            .label("within_5_pct"),
            func.count()
            .filter(
                pp.our_price > pp.avg_competitor * 1.05,
                pp.our_price <= pp.avg_competitor * 1.20,
            )
            .label("above_average"),
            func.count()
            .filter(pp.our_price > pp.avg_competitor * 1.20)
            .label("most_expensive"),
        ).select_from(product_positions)
    )

    row = distribution_result.one()
    price_position = PricePositionDistribution(
        cheapest=row.cheapest or 0,
        within_5_pct=row.within_5_pct or 0,
        above_average=row.above_average or 0,
        most_expensive=row.most_expensive or 0,
    )

    # ── 3. Products needing attention ──────────────────────────────────────
    #    Products where at least one competitor undercuts our price.

    attention_result = await db.execute(
        select(
            Product.id.label("product_id"),
            Product.title,
            Product.our_price,
            Competitor.name.label("competitor_name"),
            CompetitorProduct.last_price.label("competitor_price"),
            func.round(
                (CompetitorProduct.last_price - Product.our_price)
                / Product.our_price
                * 100,
                1,
            ).label("diff_pct"),
            CompetitorProduct.last_scraped_at.label("last_changed"),
        )
        .join(CompetitorProduct, CompetitorProduct.product_id == Product.id)
        .join(Competitor, Competitor.id == CompetitorProduct.competitor_id)
        .where(
            Product.shop_id == shop_id,
            Product.status == "active",
            CompetitorProduct.status == "active",
            CompetitorProduct.last_price.isnot(None),
            CompetitorProduct.last_price < Product.our_price,
        )
        .order_by(
            # Most undercut first (most negative diff)
            ((CompetitorProduct.last_price - Product.our_price) / Product.our_price).asc()
        )
        .limit(10)
    )

    attention_products = [
        AttentionProduct(
            product_id=r.product_id,
            title=r.title,
            our_price=float(r.our_price),
            competitor_name=r.competitor_name,
            competitor_price=float(r.competitor_price),
            diff_pct=float(r.diff_pct) if r.diff_pct is not None else 0.0,
            last_changed=r.last_changed.isoformat() if r.last_changed else None,
        )
        for r in attention_result.all()
    ]

    return {
        "summary": summary,
        "price_position": price_position,
        "attention_products": attention_products,
    }
