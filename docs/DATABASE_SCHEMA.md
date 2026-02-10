# Database Schema - Core MVP Models

## Overview

This document describes the database schema for the Price Radar MVP. The schema is designed to support:
- Multi-tenant Shopify store management
- Product tracking and competitor monitoring
- Price scraping and historical data
- Alert rules and notifications
- Subscription billing

## Entity Relationship Diagram

```
┌─────────────────┐
│     shops       │
├─────────────────┤
│ id (PK)         │
│ shopify_domain  │◄─────┐
│ access_token    │      │
│ plan            │      │
│ status          │      │
│ created_at      │      │
│ updated_at      │      │
└─────────────────┘      │
         │               │
         │ 1             │
         │               │
         │ N             │
    ┌────┴──────┬────────┴──────┬─────────────────┬─────────────────┐
    │           │               │                 │                 │
┌───▼────────┐ ┌▼────────────┐ ┌▼─────────────┐ ┌▼──────────────┐ │
│ products   │ │ competitors │ │ alert_rules  │ │subscriptions  │ │
├────────────┤ ├─────────────┤ ├──────────────┤ ├───────────────┤ │
│ id (PK)    │ │ id (PK)     │ │ id (PK)      │ │ id (PK)       │ │
│ shop_id(FK)│ │ shop_id(FK) │ │ shop_id (FK) │ │ shop_id (FK)  │ │
│ shopify_   │ │ name        │ │ type         │ │ plan          │ │
│ product_id │ │ domain      │ │ threshold_   │ │ shopify_      │ │
│ title      │ │ logo_url    │ │ pct          │ │ charge_id     │ │
│ handle     │ │ status      │ │ channels     │ │ status        │ │
│ image_url  │ │ created_at  │ │ (JSON)       │ │ current_      │ │
│ our_price  │ │ updated_at  │ │ enabled      │ │ period_start  │ │
│ currency   │ └─────────────┘ │ created_at   │ │ current_      │ │
│ variants   │        │        │ updated_at   │ │ period_end    │ │
│ (JSON)     │        │        └──────────────┘ │ created_at    │ │
│ tags       │        │               │         │ updated_at    │ │
│ status     │        │               │         └───────────────┘ │
│ created_at │        │               │                           │
│ updated_at │        │               │ 1                         │
└────────────┘        │               │                           │
     │                │               │ N                         │
     │ 1              │               │                           │
     │                │               ┌───────────────────────────┘
     │ N              │ N             │
┌────▼──────────────┐ │          ┌───▼─────────────┐
│competitor_products│◄┘          │  alert_events   │
├───────────────────┤            ├─────────────────┤
│ id (PK)           │            │ id (PK)         │
│ product_id (FK)   │◄───┐       │ alert_rule_id   │
│ competitor_id(FK) │    │       │ (FK)            │
│ url               │    │       │ competitor_     │
│ selector_config   │    │       │ product_id (FK) │
│ (JSON)            │    │       │ old_price       │
│ status            │    │       │ new_price       │
│ last_scraped_at   │    │       │ triggered_at    │
│ last_success_at   │    │       │ delivered_at    │
│ created_at        │    │       └─────────────────┘
│ updated_at        │    │
└───────────────────┘    │
     │                   │
     │ 1                 │
     │                   │
     │ N                 │
┌────▼────────────┐      │
│  price_points   │      │
├─────────────────┤      │
│ id (PK)         │      │
│ competitor_     │──────┘
│ product_id (FK) │
│ price           │
│ original_price  │
│ sale_price      │
│ currency        │
│ in_stock        │
│ scraped_at      │
│ (PARTITIONED)   │
└─────────────────┘
```

## Table Descriptions

### shops
Core tenant table storing Shopify store information.

| Column         | Type         | Constraints                | Description                          |
|----------------|--------------|----------------------------|--------------------------------------|
| id             | INTEGER      | PRIMARY KEY                | Auto-incrementing ID                 |
| shopify_domain | VARCHAR(255) | UNIQUE, NOT NULL, INDEXED  | Shop's myshopify.com domain          |
| access_token   | TEXT         | NOT NULL                   | Encrypted Shopify API access token   |
| plan           | VARCHAR(50)  | NOT NULL, DEFAULT 'free'   | Subscription plan tier               |
| status         | VARCHAR(50)  | NOT NULL, DEFAULT 'active' | Shop status (active/suspended/etc)   |
| created_at     | TIMESTAMP    | NOT NULL, DEFAULT NOW()    | Shop creation timestamp              |
| updated_at     | TIMESTAMP    | NOT NULL, DEFAULT NOW()    | Last update timestamp                |

**Indexes:**
- `ix_shops_shopify_domain` (UNIQUE)

**Plans:** `free`, `basic`, `pro`, `enterprise`

**Statuses:** `active`, `suspended`, `cancelled`

---

### products
Merchant's products from their Shopify store.

| Column             | Type          | Constraints                 | Description                        |
|--------------------|---------------|-----------------------------|-----------------------------------|
| id                 | INTEGER       | PRIMARY KEY                 | Auto-incrementing ID              |
| shop_id            | INTEGER       | FK → shops.id, NOT NULL     | Owner shop reference              |
| shopify_product_id | VARCHAR(255)  | NOT NULL, INDEXED           | Shopify's product ID              |
| title              | VARCHAR(500)  | NOT NULL                    | Product title                     |
| handle             | VARCHAR(255)  | NOT NULL                    | Shopify product handle (URL slug) |
| image_url          | VARCHAR(1000) | NULL                        | Primary product image             |
| our_price          | NUMERIC(10,2) | NOT NULL                    | Merchant's current price          |
| currency           | VARCHAR(3)    | NOT NULL, DEFAULT 'USD'     | ISO 4217 currency code            |
| variants           | JSON          | NULL                        | Product variants data             |
| tags               | TEXT          | NULL                        | Comma-separated tags              |
| status             | VARCHAR(50)   | NOT NULL, DEFAULT 'active'  | Product status                    |
| created_at         | TIMESTAMP     | NOT NULL, DEFAULT NOW()     | Creation timestamp                |
| updated_at         | TIMESTAMP     | NOT NULL, DEFAULT NOW()     | Last update timestamp             |

**Indexes:**
- `ix_products_shop_id`
- `ix_products_shopify_product_id`

**Foreign Keys:**
- `shop_id` → `shops.id` (CASCADE DELETE)

---

### competitors
Competitor stores being tracked by merchants.

| Column     | Type          | Constraints                 | Description                  |
|------------|---------------|-----------------------------|------------------------------|
| id         | INTEGER       | PRIMARY KEY                 | Auto-incrementing ID         |
| shop_id    | INTEGER       | FK → shops.id, NOT NULL     | Owner shop reference         |
| name       | VARCHAR(255)  | NOT NULL                    | Competitor name              |
| domain     | VARCHAR(255)  | NOT NULL                    | Competitor website domain    |
| logo_url   | VARCHAR(1000) | NULL                        | Competitor logo URL          |
| status     | VARCHAR(50)   | NOT NULL, DEFAULT 'active'  | Competitor status            |
| created_at | TIMESTAMP     | NOT NULL, DEFAULT NOW()     | Creation timestamp           |
| updated_at | TIMESTAMP     | NOT NULL, DEFAULT NOW()     | Last update timestamp        |

**Indexes:**
- `ix_competitors_shop_id`

**Foreign Keys:**
- `shop_id` → `shops.id` (CASCADE DELETE)

---

### competitor_products
Links merchant products to competitor URLs for price tracking.

| Column            | Type          | Constraints                    | Description                          |
|-------------------|---------------|--------------------------------|--------------------------------------|
| id                | INTEGER       | PRIMARY KEY                    | Auto-incrementing ID                 |
| product_id        | INTEGER       | FK → products.id, NOT NULL     | Merchant product reference           |
| competitor_id     | INTEGER       | FK → competitors.id, NOT NULL  | Competitor reference                 |
| url               | VARCHAR(2000) | NOT NULL                       | Competitor product page URL          |
| selector_config   | JSON          | NOT NULL                       | CSS selectors for scraping           |
| status            | VARCHAR(50)   | NOT NULL, DEFAULT 'active'     | Tracking status                      |
| last_scraped_at   | TIMESTAMP     | NULL                           | Last scrape attempt                  |
| last_success_at   | TIMESTAMP     | NULL                           | Last successful scrape               |
| created_at        | TIMESTAMP     | NOT NULL, DEFAULT NOW()        | Creation timestamp                   |
| updated_at        | TIMESTAMP     | NOT NULL, DEFAULT NOW()        | Last update timestamp                |

**Indexes:**
- `ix_competitor_products_product_id`
- `ix_competitor_products_competitor_id`

**Foreign Keys:**
- `product_id` → `products.id` (CASCADE DELETE)
- `competitor_id` → `competitors.id` (CASCADE DELETE)

**selector_config JSON structure:**
```json
{
  "price": ".price-selector",
  "original_price": ".original-price",
  "in_stock": ".availability",
  "currency": ".currency-symbol"
}
```

**Statuses:** `active`, `failed`, `paused`

---

### price_points
Historical price data scraped from competitor products. **Partitioned by month** for performance.

| Column                | Type          | Constraints                           | Description                    |
|-----------------------|---------------|---------------------------------------|--------------------------------|
| id                    | INTEGER       | PRIMARY KEY                           | Auto-incrementing ID           |
| competitor_product_id | INTEGER       | FK → competitor_products.id, NOT NULL | Competitor product reference   |
| price                 | NUMERIC(10,2) | NOT NULL                              | Current price                  |
| original_price        | NUMERIC(10,2) | NULL                                  | Original/MSRP price            |
| sale_price            | NUMERIC(10,2) | NULL                                  | Sale price if on sale          |
| currency              | VARCHAR(3)    | NOT NULL, DEFAULT 'USD'               | ISO 4217 currency code         |
| in_stock              | BOOLEAN       | NOT NULL, DEFAULT TRUE                | Availability status            |
| scraped_at            | TIMESTAMP     | NOT NULL, DEFAULT NOW(), INDEXED      | When price was scraped         |

**Indexes:**
- `ix_price_points_competitor_product_id`
- `ix_price_points_scraped_at`

**Foreign Keys:**
- `competitor_product_id` → `competitor_products.id` (CASCADE DELETE)

**Partitioning:**
Table is partitioned by `scraped_at` using RANGE partitioning by month for optimal query performance and data management.

---

### alert_rules
Defines conditions for triggering price alerts.

| Column        | Type         | Constraints                | Description                          |
|---------------|--------------|----------------------------|--------------------------------------|
| id            | INTEGER      | PRIMARY KEY                | Auto-incrementing ID                 |
| shop_id       | INTEGER      | FK → shops.id, NOT NULL    | Owner shop reference                 |
| type          | VARCHAR(50)  | NOT NULL                   | Alert type                           |
| threshold_pct | NUMERIC(5,2) | NULL                       | Percentage threshold for alert       |
| channels      | JSON         | NOT NULL                   | Notification channels configuration  |
| enabled       | BOOLEAN      | NOT NULL, DEFAULT TRUE     | Whether rule is active               |
| created_at    | TIMESTAMP    | NOT NULL, DEFAULT NOW()    | Creation timestamp                   |
| updated_at    | TIMESTAMP    | NOT NULL, DEFAULT NOW()    | Last update timestamp                |

**Indexes:**
- `ix_alert_rules_shop_id`

**Foreign Keys:**
- `shop_id` → `shops.id` (CASCADE DELETE)

**Alert Types:** `undercut`, `price_change`, `stock_change`

**channels JSON structure:**
```json
{
  "email": true,
  "slack": false,
  "webhook": "https://example.com/webhook"
}
```

---

### alert_events
Records when alert rules are triggered.

| Column                | Type          | Constraints                           | Description                    |
|-----------------------|---------------|---------------------------------------|--------------------------------|
| id                    | INTEGER       | PRIMARY KEY                           | Auto-incrementing ID           |
| alert_rule_id         | INTEGER       | FK → alert_rules.id, NOT NULL         | Alert rule that triggered      |
| competitor_product_id | INTEGER       | FK → competitor_products.id, NOT NULL | Affected product               |
| old_price             | NUMERIC(10,2) | NULL                                  | Previous price                 |
| new_price             | NUMERIC(10,2) | NOT NULL                              | New price that triggered alert |
| triggered_at          | TIMESTAMP     | NOT NULL, DEFAULT NOW(), INDEXED      | When alert was triggered       |
| delivered_at          | TIMESTAMP     | NULL                                  | When notification was sent     |

**Indexes:**
- `ix_alert_events_alert_rule_id`
- `ix_alert_events_competitor_product_id`
- `ix_alert_events_triggered_at`

**Foreign Keys:**
- `alert_rule_id` → `alert_rules.id` (CASCADE DELETE)
- `competitor_product_id` → `competitor_products.id` (CASCADE DELETE)

---

### subscriptions
Tracks Shopify billing subscriptions and plan information.

| Column               | Type         | Constraints                 | Description                        |
|----------------------|--------------|-----------------------------|------------------------------------|
| id                   | INTEGER      | PRIMARY KEY                 | Auto-incrementing ID               |
| shop_id              | INTEGER      | FK → shops.id, NOT NULL     | Owner shop reference               |
| plan                 | VARCHAR(50)  | NOT NULL                    | Subscription plan tier             |
| shopify_charge_id    | VARCHAR(255) | UNIQUE, NULL, INDEXED       | Shopify recurring charge ID        |
| status               | VARCHAR(50)  | NOT NULL, DEFAULT 'active'  | Subscription status                |
| current_period_start | TIMESTAMP    | NOT NULL                    | Current billing period start       |
| current_period_end   | TIMESTAMP    | NOT NULL                    | Current billing period end         |
| created_at           | TIMESTAMP    | NOT NULL, DEFAULT NOW()     | Creation timestamp                 |
| updated_at           | TIMESTAMP    | NOT NULL, DEFAULT NOW()     | Last update timestamp              |

**Indexes:**
- `ix_subscriptions_shop_id`
- `ix_subscriptions_shopify_charge_id` (UNIQUE)

**Foreign Keys:**
- `shop_id` → `shops.id` (CASCADE DELETE)

**Plans:** `free`, `basic`, `pro`, `enterprise`

**Statuses:** `active`, `cancelled`, `expired`, `pending`

---

## Migration Notes

### From shopify_stores to shops

The migration automatically transfers data from the legacy `shopify_stores` table to the new `shops` table:

- `shop_domain` → `shopify_domain`
- `is_active` → `status` (TRUE → 'active', FALSE → 'suspended')
- `installed_at` → `created_at` and `updated_at`
- Default plan set to 'free'

### Partitioning Strategy

The `price_points` table is designed to be partitioned by month on the `scraped_at` column. This provides:
- Improved query performance for time-range queries
- Easier data archival and retention management
- Better index efficiency

Partition creation can be automated or done manually as needed.

## Data Retention

Recommended retention policies:
- **price_points**: Keep 12 months of data, archive older
- **alert_events**: Keep 6 months of data
- **shops**: Soft delete (status = 'cancelled')
- **products**: Soft delete (status = 'archived')

## Performance Considerations

1. **Indexes**: All foreign keys are indexed for optimal join performance
2. **Partitioning**: price_points table partitioned by month
3. **Timestamps**: All tables include created_at/updated_at for audit trails
4. **Cascading Deletes**: Foreign keys use CASCADE DELETE for data integrity
5. **JSON Fields**: Used sparingly for semi-structured data (variants, channels, selector_config)

## Security

- **access_token**: Must be encrypted at rest using application-level encryption
- **PII Data**: Shop domain is the only potentially sensitive field
- **Audit Trail**: All tables include timestamps for change tracking
