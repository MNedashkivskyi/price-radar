"""add competitor_product scraping columns

Revision ID: b1c3d4e5f6a7
Revises: af4e8a73e768
Create Date: 2026-02-17 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c3d4e5f6a7"
down_revision: str | None = "af4e8a73e768"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add scraping-related columns to competitor_products."""
    op.add_column(
        "competitor_products",
        sa.Column("last_price", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.add_column(
        "competitor_products",
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "competitor_products",
        sa.Column("fetch_strategy", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    """Remove scraping-related columns from competitor_products."""
    op.drop_column("competitor_products", "fetch_strategy")
    op.drop_column("competitor_products", "consecutive_failures")
    op.drop_column("competitor_products", "last_price")
