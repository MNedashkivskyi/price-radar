"""Database models."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.src.price_radar.infrastructure.database import Base


class Shop(Base):  # type: ignore[misc]
    """Shop (Shopify store) model."""

    __tablename__ = "shops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    shopify_domain: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    access_token: Mapped[str] = mapped_column(Text, nullable=False)  # Encrypted
    plan: Mapped[str] = mapped_column(
        String(50), nullable=False, default="free"
    )  # free, basic, pro, enterprise
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active"
    )  # active, suspended, cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    products: Mapped[list["Product"]] = relationship("Product", back_populates="shop")
    competitors: Mapped[list["Competitor"]] = relationship("Competitor", back_populates="shop")
    alert_rules: Mapped[list["AlertRule"]] = relationship("AlertRule", back_populates="shop")
    subscriptions: Mapped[list["Subscription"]] = relationship(
        "Subscription", back_populates="shop"
    )

    def __repr__(self) -> str:
        """String representation."""
        return f"<Shop(shopify_domain='{self.shopify_domain}', plan='{self.plan}')>"


class Product(Base):  # type: ignore[misc]
    """Product model - products from merchant's Shopify store."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    shop_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    shopify_product_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )  # Shopify's product ID
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    handle: Mapped[str] = mapped_column(String(255), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    our_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")  # ISO 4217
    variants: Mapped[dict] = mapped_column(JSON, nullable=True)  # Store variant data as JSON
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)  # Comma-separated tags
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active"
    )  # active, archived
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    shop: Mapped["Shop"] = relationship("Shop", back_populates="products")
    competitor_products: Mapped[list["CompetitorProduct"]] = relationship(
        "CompetitorProduct", back_populates="product"
    )

    def __repr__(self) -> str:
        """String representation."""
        return f"<Product(title='{self.title}', our_price={self.our_price})>"


class Competitor(Base):  # type: ignore[misc]
    """Competitor model - competitor stores being tracked."""

    __tablename__ = "competitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    shop_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    logo_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active"
    )  # active, inactive
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    shop: Mapped["Shop"] = relationship("Shop", back_populates="competitors")
    competitor_products: Mapped[list["CompetitorProduct"]] = relationship(
        "CompetitorProduct", back_populates="competitor"
    )

    def __repr__(self) -> str:
        """String representation."""
        return f"<Competitor(name='{self.name}', domain='{self.domain}')>"


class CompetitorProduct(Base):  # type: ignore[misc]
    """Competitor product model - links products to competitor URLs for tracking."""

    __tablename__ = "competitor_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    competitor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    selector_config: Mapped[dict] = mapped_column(
        JSON, nullable=False
    )  # CSS selectors for scraping
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active"
    )  # active, failed, paused
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_price: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )  # Cached last extracted price for quick comparison / dedup
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # Reset to 0 on success; status → "failed" after threshold
    fetch_strategy: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # httpx, playwright, scraper_api — caches last working method
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    product: Mapped["Product"] = relationship("Product", back_populates="competitor_products")
    competitor: Mapped["Competitor"] = relationship(
        "Competitor", back_populates="competitor_products"
    )
    price_points: Mapped[list["PricePoint"]] = relationship(
        "PricePoint", back_populates="competitor_product"
    )

    def __repr__(self) -> str:
        """String representation."""
        return f"<CompetitorProduct(url='{self.url}', status='{self.status}')>"


class PricePoint(Base):  # type: ignore[misc]
    """Price point model - historical price data scraped from competitors."""

    __tablename__ = "price_points"
    __table_args__ = {"postgresql_partition_by": "RANGE (scraped_at)"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    competitor_product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("competitor_products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    original_price: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )  # Regular price before sale
    sale_price: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )  # Actual sale price if on sale
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    in_stock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )

    # Relationships
    competitor_product: Mapped["CompetitorProduct"] = relationship(
        "CompetitorProduct", back_populates="price_points"
    )

    def __repr__(self) -> str:
        """String representation."""
        return f"<PricePoint(price={self.price}, scraped_at='{self.scraped_at}')>"


class AlertRule(Base):  # type: ignore[misc]
    """Alert rule model - defines conditions for triggering price alerts."""

    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    shop_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # undercut, price_change, stock_change
    threshold_pct: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )  # Percentage threshold
    channels: Mapped[dict] = mapped_column(
        JSON, nullable=False
    )  # {email: true, slack: false, webhook: "url"}
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    shop: Mapped["Shop"] = relationship("Shop", back_populates="alert_rules")
    alert_events: Mapped[list["AlertEvent"]] = relationship(
        "AlertEvent", back_populates="alert_rule"
    )

    def __repr__(self) -> str:
        """String representation."""
        return f"<AlertRule(type='{self.type}', enabled={self.enabled})>"


class AlertEvent(Base):  # type: ignore[misc]
    """Alert event model - records when alert rules are triggered."""

    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    alert_rule_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    competitor_product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("competitor_products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    old_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    new_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    alert_rule: Mapped["AlertRule"] = relationship("AlertRule", back_populates="alert_events")

    def __repr__(self) -> str:
        """String representation."""
        return f"<AlertEvent(old_price={self.old_price}, new_price={self.new_price})>"


class Subscription(Base):  # type: ignore[misc]
    """Subscription model - tracks Shopify billing subscriptions."""

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    shop_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan: Mapped[str] = mapped_column(String(50), nullable=False)  # free, basic, pro, enterprise
    shopify_charge_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active"
    )  # active, cancelled, expired, pending
    current_period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    shop: Mapped["Shop"] = relationship("Shop", back_populates="subscriptions")

    def __repr__(self) -> str:
        """String representation."""
        return f"<Subscription(plan='{self.plan}', status='{self.status}')>"
