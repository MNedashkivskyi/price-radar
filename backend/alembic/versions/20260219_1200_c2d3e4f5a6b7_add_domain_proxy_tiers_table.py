"""add domain_proxy_tiers table

Revision ID: c2d3e4f5a6b7
Revises: b1c3d4e5f6a7
Create Date: 2026-02-19 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2d3e4f5a6b7"
down_revision: str | None = "b1c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create domain_proxy_tiers table for proxy tier classification."""
    op.create_table(
        "domain_proxy_tiers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "domain",
            sa.String(length=255),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column(
            "tier",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'direct'"),
        ),
        sa.Column(
            "classified_by",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'auto'"),
        ),
        sa.Column(
            "last_verified_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "success_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "failure_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    """Drop domain_proxy_tiers table."""
    op.drop_table("domain_proxy_tiers")
