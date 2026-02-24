"""add dashboard query indexes

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-02-24 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3e4f5a6b7c8"
down_revision: str | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add indexes to speed up dashboard overview queries.

    - Partial index on competitor_products(product_id, last_price) for active rows
      speeds up price position distribution and attention product queries.
    """
    op.create_index(
        "ix_competitor_products_active_price",
        "competitor_products",
        ["product_id", "last_price"],
        postgresql_where="status = 'active'",
    )


def downgrade() -> None:
    """Remove dashboard query indexes."""
    op.drop_index("ix_competitor_products_active_price", table_name="competitor_products")
