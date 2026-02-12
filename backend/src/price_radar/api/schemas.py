"""Pydantic schemas for API request/response validation."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductCreateRequest(BaseModel):
    """Schema for creating a product manually."""

    title: str = Field(..., min_length=1, max_length=255, description="Product title")
    handle: str | None = Field(None, max_length=255, description="URL-friendly product handle")
    image_url: str | None = Field(None, max_length=500, description="Product image URL")
    our_price: Decimal = Field(..., gt=0, description="Product price (must be positive)")
    currency: str = Field(default="USD", max_length=3, description="Currency code (ISO 4217)")
    variants: dict[str, Any] | None = Field(None, description="Product variants as JSON (optional)")
    tags: list[str] | None = Field(None, description="Product tags")
    shopify_product_id: str | None = Field(
        None, description="Shopify product ID if synced from Shopify"
    )

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        """Validate currency code format."""
        if not v.isupper() or len(v) != 3:
            raise ValueError("Currency must be a 3-letter uppercase ISO code (e.g., USD, EUR)")
        return v

    @field_validator("handle")
    @classmethod
    def validate_handle(cls, v: str | None) -> str | None:
        """Validate handle is URL-friendly."""
        # Handle should only contain lowercase letters, numbers, and hyphens
        if v is not None and not all(c.islower() or c.isdigit() or c == "-" for c in v):
            raise ValueError("Handle must contain only lowercase letters, numbers, and hyphens")
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str] | None) -> list[str] | None:
        """Validate tags are non-empty strings."""
        if v is not None:
            for tag in v:
                if not tag or not tag.strip():
                    raise ValueError("Tags must be non-empty strings")
        return v


class ProductUpdateRequest(BaseModel):
    """Schema for updating a product manually."""

    title: str | None = Field(None, min_length=1, max_length=255)
    handle: str | None = Field(None, max_length=255)
    image_url: str | None = Field(None, max_length=500)
    our_price: Decimal | None = Field(None, gt=0)
    currency: str | None = Field(None, max_length=3)
    variants: dict[str, Any] | None = None
    tags: list[str] | None = None

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str | None) -> str | None:
        """Validate currency code format."""
        if v is not None and (not v.isupper() or len(v) != 3):
            raise ValueError("Currency must be a 3-letter uppercase ISO code (e.g., USD, EUR)")
        return v

    @field_validator("handle")
    @classmethod
    def validate_handle(cls, v: str | None) -> str | None:
        """Validate handle is URL-friendly."""
        if v is not None and not all(c.islower() or c.isdigit() or c == "-" for c in v):
            raise ValueError("Handle must contain only lowercase letters, numbers, and hyphens")
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str] | None) -> list[str] | None:
        """Validate tags are non-empty strings."""
        if v is not None:
            for tag in v:
                if not tag or not tag.strip():
                    raise ValueError("Tags must be non-empty strings")
        return v


class ProductResponse(BaseModel):
    """Schema for product response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    shopify_product_id: str | None
    title: str
    handle: str | None
    image_url: str | None
    our_price: Decimal
    currency: str
    variants: dict[str, Any] | None
    tags: list[str] | None
    status: str
    created_at: datetime
    updated_at: datetime
