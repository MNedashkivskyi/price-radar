"""Database models."""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from price_radar.infrastructure.database import Base


class ShopifyStoreModel(Base):  # type: ignore[misc]
    """Shopify store database model."""

    __tablename__ = "shopify_stores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    shop_domain: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)  # Encrypted
    scopes: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    uninstalled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        """String representation."""
        return f"<ShopifyStore(shop_domain='{self.shop_domain}', is_active={self.is_active})>"
