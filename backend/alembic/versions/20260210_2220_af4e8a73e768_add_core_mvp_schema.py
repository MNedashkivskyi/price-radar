"""add_core_mvp_schema

Revision ID: af4e8a73e768
Revises: 002
Create Date: 2026-02-10 22:20:10.088355

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "af4e8a73e768"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all core MVP tables."""
    # Create shops table (replaces shopify_stores)
    op.create_table(
        "shops",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shopify_domain", sa.String(length=255), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("plan", sa.String(length=50), nullable=False, server_default="free"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_shops_id"), "shops", ["id"], unique=False)
    op.create_index(op.f("ix_shops_shopify_domain"), "shops", ["shopify_domain"], unique=True)

    # Create products table
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("shopify_product_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("handle", sa.String(length=255), nullable=False),
        sa.Column("image_url", sa.String(length=1000), nullable=True),
        sa.Column("our_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("variants", JSON, nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_products_id"), "products", ["id"], unique=False)
    op.create_index(op.f("ix_products_shop_id"), "products", ["shop_id"], unique=False)
    op.create_index(
        op.f("ix_products_shopify_product_id"), "products", ["shopify_product_id"], unique=False
    )

    # Create competitors table
    op.create_table(
        "competitors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("logo_url", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_competitors_id"), "competitors", ["id"], unique=False)
    op.create_index(op.f("ix_competitors_shop_id"), "competitors", ["shop_id"], unique=False)

    # Create competitor_products table
    op.create_table(
        "competitor_products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("competitor_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("selector_config", JSON, nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("last_scraped_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["competitor_id"], ["competitors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_competitor_products_id"), "competitor_products", ["id"], unique=False)
    op.create_index(
        op.f("ix_competitor_products_product_id"),
        "competitor_products",
        ["product_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_competitor_products_competitor_id"),
        "competitor_products",
        ["competitor_id"],
        unique=False,
    )

    # Create price_points table (partitioned by month)
    # Note: Partitioning setup will be done separately as it requires special handling
    op.create_table(
        "price_points",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("competitor_product_id", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("original_price", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("sale_price", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("in_stock", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("scraped_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(
            ["competitor_product_id"], ["competitor_products.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_price_points_id"), "price_points", ["id"], unique=False)
    op.create_index(
        op.f("ix_price_points_competitor_product_id"),
        "price_points",
        ["competitor_product_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_price_points_scraped_at"), "price_points", ["scraped_at"], unique=False
    )

    # Create alert_rules table
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("threshold_pct", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("channels", JSON, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_alert_rules_id"), "alert_rules", ["id"], unique=False)
    op.create_index(op.f("ix_alert_rules_shop_id"), "alert_rules", ["shop_id"], unique=False)

    # Create alert_events table
    op.create_table(
        "alert_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("alert_rule_id", sa.Integer(), nullable=False),
        sa.Column("competitor_product_id", sa.Integer(), nullable=False),
        sa.Column("old_price", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("new_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("triggered_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["alert_rule_id"], ["alert_rules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["competitor_product_id"], ["competitor_products.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_alert_events_id"), "alert_events", ["id"], unique=False)
    op.create_index(
        op.f("ix_alert_events_alert_rule_id"), "alert_events", ["alert_rule_id"], unique=False
    )
    op.create_index(
        op.f("ix_alert_events_competitor_product_id"),
        "alert_events",
        ["competitor_product_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_alert_events_triggered_at"), "alert_events", ["triggered_at"], unique=False
    )

    # Create subscriptions table
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("plan", sa.String(length=50), nullable=False),
        sa.Column("shopify_charge_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("current_period_start", sa.DateTime(), nullable=False),
        sa.Column("current_period_end", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_subscriptions_id"), "subscriptions", ["id"], unique=False)
    op.create_index(op.f("ix_subscriptions_shop_id"), "subscriptions", ["shop_id"], unique=False)
    op.create_index(
        op.f("ix_subscriptions_shopify_charge_id"),
        "subscriptions",
        ["shopify_charge_id"],
        unique=True,
    )

    # Migrate data from shopify_stores to shops
    op.execute(
        """
        INSERT INTO shops (id, shopify_domain, access_token, plan, status, created_at, updated_at)
        SELECT id, shop_domain, access_token, 'free',
               CASE WHEN is_active THEN 'active' ELSE 'suspended' END,
               installed_at, installed_at
        FROM shopify_stores
        """
    )

    # Drop old shopify_stores table
    op.drop_index(op.f("ix_shopify_stores_shop_domain"), table_name="shopify_stores")
    op.drop_index(op.f("ix_shopify_stores_id"), table_name="shopify_stores")
    op.drop_table("shopify_stores")


def downgrade() -> None:
    """Drop all core MVP tables and restore shopify_stores."""
    # Recreate shopify_stores table
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

    # Migrate data back from shops to shopify_stores
    op.execute(
        """
        INSERT INTO shopify_stores (id, shop_domain, access_token, scopes, is_active, installed_at)
        SELECT id, shopify_domain, access_token, 'read_products,write_products,read_orders',
               CASE WHEN status = 'active' THEN TRUE ELSE FALSE END,
               created_at
        FROM shops
        """
    )

    # Drop all new tables in reverse order (respecting foreign keys)
    op.drop_index(op.f("ix_subscriptions_shopify_charge_id"), table_name="subscriptions")
    op.drop_index(op.f("ix_subscriptions_shop_id"), table_name="subscriptions")
    op.drop_index(op.f("ix_subscriptions_id"), table_name="subscriptions")
    op.drop_table("subscriptions")

    op.drop_index(op.f("ix_alert_events_triggered_at"), table_name="alert_events")
    op.drop_index(op.f("ix_alert_events_competitor_product_id"), table_name="alert_events")
    op.drop_index(op.f("ix_alert_events_alert_rule_id"), table_name="alert_events")
    op.drop_index(op.f("ix_alert_events_id"), table_name="alert_events")
    op.drop_table("alert_events")

    op.drop_index(op.f("ix_alert_rules_shop_id"), table_name="alert_rules")
    op.drop_index(op.f("ix_alert_rules_id"), table_name="alert_rules")
    op.drop_table("alert_rules")

    op.drop_index(op.f("ix_price_points_scraped_at"), table_name="price_points")
    op.drop_index(op.f("ix_price_points_competitor_product_id"), table_name="price_points")
    op.drop_index(op.f("ix_price_points_id"), table_name="price_points")
    op.drop_table("price_points")

    op.drop_index(op.f("ix_competitor_products_competitor_id"), table_name="competitor_products")
    op.drop_index(op.f("ix_competitor_products_product_id"), table_name="competitor_products")
    op.drop_index(op.f("ix_competitor_products_id"), table_name="competitor_products")
    op.drop_table("competitor_products")

    op.drop_index(op.f("ix_competitors_shop_id"), table_name="competitors")
    op.drop_index(op.f("ix_competitors_id"), table_name="competitors")
    op.drop_table("competitors")

    op.drop_index(op.f("ix_products_shopify_product_id"), table_name="products")
    op.drop_index(op.f("ix_products_shop_id"), table_name="products")
    op.drop_index(op.f("ix_products_id"), table_name="products")
    op.drop_table("products")

    op.drop_index(op.f("ix_shops_shopify_domain"), table_name="shops")
    op.drop_index(op.f("ix_shops_id"), table_name="shops")
    op.drop_table("shops")
