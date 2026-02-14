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


# Competitor Schemas


class CompetitorCreateRequest(BaseModel):
    """Schema for creating a competitor."""

    name: str = Field(..., min_length=1, max_length=255, description="Competitor name")
    domain: str = Field(..., min_length=1, max_length=255, description="Competitor domain")
    logo_url: str | None = Field(None, max_length=1000, description="Competitor logo URL")

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        """Validate domain format."""
        # Remove protocol if present
        domain = v.lower().replace("http://", "").replace("https://", "").replace("www.", "")
        # Remove trailing slash
        domain = domain.rstrip("/")
        # Basic validation
        if not domain or "." not in domain:
            raise ValueError("Domain must be a valid domain name (e.g., example.com)")
        return domain


class CompetitorResponse(BaseModel):
    """Schema for competitor response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    shop_id: int
    name: str
    domain: str
    logo_url: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class CompetitorProductCreateRequest(BaseModel):
    """Schema for creating a single competitor product mapping."""

    product_id: int = Field(..., description="Internal product ID")
    competitor_id: int = Field(..., description="Competitor ID")
    url: str = Field(..., min_length=1, max_length=2000, description="Competitor product URL")
    selector_config: dict[str, Any] | None = Field(
        default_factory=dict, description="CSS selectors for scraping"
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate URL format."""
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class CompetitorProductResponse(BaseModel):
    """Schema for competitor product response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    competitor_id: int
    url: str
    selector_config: dict[str, Any]
    status: str
    last_scraped_at: datetime | None
    last_success_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BulkUploadRequest(BaseModel):
    """Schema for bulk CSV upload."""

    csv_data: str = Field(..., description="CSV data as string")

    @field_validator("csv_data")
    @classmethod
    def validate_csv_data(cls, v: str) -> str:
        """Validate CSV has content."""
        if not v or not v.strip():
            raise ValueError("CSV data cannot be empty")
        return v


class BulkUploadResponse(BaseModel):
    """Schema for bulk upload response."""

    success_count: int = Field(..., description="Number of successfully processed rows")
    error_count: int = Field(..., description="Number of rows with errors")
    errors: list[dict[str, Any]] = Field(
        default_factory=list, description="List of errors with row numbers"
    )
    created_competitors: list[str] = Field(
        default_factory=list, description="List of auto-created competitor domains"
    )
