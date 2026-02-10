"""Add shopify_stores table

Revision ID: 002
Revises: 001
Create Date: 2026-02-10 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shopify_stores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_domain", sa.String(length=255), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("scopes", sa.String(length=500), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("installed_at", sa.DateTime(), nullable=False),
        sa.Column("uninstalled_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_shopify_stores_id"), "shopify_stores", ["id"], unique=False)
    op.create_index(
        op.f("ix_shopify_stores_shop_domain"), "shopify_stores", ["shop_domain"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_shopify_stores_shop_domain"), table_name="shopify_stores")
    op.drop_index(op.f("ix_shopify_stores_id"), table_name="shopify_stores")
    op.drop_table("shopify_stores")
