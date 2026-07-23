# Data dictionary

The source data NovaSupply ingests. This describes the *raw* entities as they land in
the raw zone, before any dbt transformation. It grows as the project does.

All money is in euros. Dates are ISO (`YYYY-MM-DD`). Synthetic data generated with
Faker using a French locale, so names, cities and regions look French.

## Raw zone layout

```
data/raw/
├── suppliers/suppliers.csv                 current-state dimension (overwritten each run)
├── products/products.csv                   current-state dimension
├── stores/stores.csv                       current-state dimension
├── sales/dt=YYYY-MM-DD/sales.csv           daily fact, partitioned by date
├── inventory/dt=YYYY-MM-DD/inventory.csv   daily fact, partitioned by date
└── purchase_orders/dt=YYYY-MM-DD/purchase_orders.csv   daily fact, partitioned by date
```

Dimensions are small and land as a single current-state file. The three facts are
emitted per day into a `dt=` partition, mirroring how the same data will sit in S3.

## Entities

### suppliers (dimension)

| Column | Type | Notes |
|---|---|---|
| supplier_id | string | Primary key, e.g. `SUP-0007` |
| supplier_name | string | Company name |
| country | string | Country of origin |
| city | string | |
| nominal_lead_time_days | int | Contracted days from order to delivery |
| reliability_score | float | 0–1; higher means more often on time. Drives delivery delays |
| valid_from | date | When this version of the record took effect (feeds SCD2 later) |

### products (dimension)

| Column | Type | Notes |
|---|---|---|
| product_id | string | Primary key / SKU, e.g. `SKU-00042` |
| product_name | string | |
| category | string | Épicerie, Frais, Boissons, Hygiène, Surgelés |
| supplier_id | string | Foreign key to suppliers |
| unit_cost_eur | float | What NovaSupply pays |
| unit_price_eur | float | Shelf price |

### stores (dimension)

| Column | Type | Notes |
|---|---|---|
| store_id | string | Primary key, e.g. `STO-003` |
| store_name | string | |
| city | string | French city |
| region | string | French administrative region |

### sales (fact, partitioned by day)

| Column | Type | Notes |
|---|---|---|
| sale_id | string | Primary key |
| sale_date | date | Partition key |
| store_id | string | FK to stores |
| product_id | string | FK to products |
| quantity | int | Units sold on the line |
| unit_price_eur | float | Price at time of sale |
| discount_pct | float | 0–1 |
| amount_eur | float | quantity × unit_price × (1 − discount) |

### inventory_snapshots (fact, partitioned by day)

| Column | Type | Notes |
|---|---|---|
| snapshot_date | date | Partition key |
| store_id | string | FK to stores |
| product_id | string | FK to products |
| on_hand_qty | int | Units physically in stock |
| reorder_point | int | Stock level that should trigger a replenishment order |
| in_transit_qty | int | Units already ordered but not yet delivered |

### purchase_orders (fact, partitioned by day of order)

| Column | Type | Notes |
|---|---|---|
| po_id | string | Primary key |
| order_date | date | Partition key; when the order was placed |
| supplier_id | string | FK to suppliers |
| product_id | string | FK to products |
| store_id | string | Destination store |
| ordered_qty | int | Units ordered |
| promised_date | date | Delivery date the supplier committed to |
| actual_delivery_date | date | When it actually arrived; null if still open |
| received_qty | int | Units received; may be less than ordered |

The gap between `promised_date` and `actual_delivery_date` is the supplier-delay signal
the whole platform exists to surface. dbt derives the delay downstream; the raw table
just records the dates.

---

# Marts

The star schema analysts and the dashboard query. Four dimensions, three facts, joined on
natural keys. Everything below is built by dbt and exists identically on DuckDB and
Snowflake.

## dim_suppliers

| Column | Type | Notes |
|---|---|---|
| supplier_id | string | Primary key |
| supplier_name | string | |
| country, city | string | |
| nominal_lead_time_days | int | Contracted order-to-delivery days |
| reliability_score | float | 0–1; higher means more deliveries on time |
| reliability_tier | string | Banded score: High (≥0.95), Medium (≥0.85), Low |
| valid_from | date | |

`dim_suppliers_secure` is a Snowflake-only secure view over this table that restricts
`supplier_name` and `reliability_score` by role. See ADR 0006.

## dim_products

| Column | Type | Notes |
|---|---|---|
| product_id | string | Primary key (SKU) |
| product_name, category | string | |
| supplier_id | string | FK to dim_suppliers |
| unit_cost_eur, unit_price_eur | float | |
| unit_margin_eur | float | price − cost |
| margin_pct | float | Share of shelf price that is margin |

## dim_stores

| Column | Type | Notes |
|---|---|---|
| store_id | string | Primary key |
| store_name, city, region | string | French regions |

## dim_date

One row per day of loaded history, derived from the dates present in the inventory fact.

| Column | Type | Notes |
|---|---|---|
| date_day | date | Primary key |
| year, month, day_of_month | int | |
| iso_day_of_week | int | 1 = Monday, 7 = Sunday |
| iso_week | int | |
| weekday_name | string | |
| is_weekend | bool | Saturday or Sunday |

## fct_sales

Grain: one row per sale line — store × SKU × day. Materialised incrementally on
`sale_date` with `delete+insert` on `sale_id` (ADR 0003).

| Column | Type | Notes |
|---|---|---|
| sale_id | string | Degenerate dimension; unique |
| sale_date | date | FK to dim_date |
| store_id, product_id | string | FKs |
| quantity | int | Units sold, always ≥ 1 |
| unit_price_eur, discount_pct | float | |
| amount_eur | float | quantity × price × (1 − discount) |

## fct_inventory

Grain: one row per store × SKU × day.

| Column | Type | Notes |
|---|---|---|
| snapshot_date | date | FK to dim_date |
| store_id, product_id | string | FKs |
| on_hand_qty | int | Units in stock, never negative |
| reorder_point | int | Level that should trigger replenishment |
| in_transit_qty | int | Ordered but not yet delivered |
| avg_daily_units | float | Trailing 28-day demand rate |
| is_stockout | bool | on_hand_qty = 0 |
| below_reorder_point | bool | Often true while a delivery is in flight — not itself a problem |
| days_of_cover | float | on_hand ÷ demand rate; null when there is no recent demand |

## fct_purchase_orders

Grain: one row per replenishment order.

| Column | Type | Notes |
|---|---|---|
| po_id | string | Primary key |
| order_date | date | |
| supplier_id, product_id, store_id | string | FKs |
| ordered_qty, received_qty | int | received may be short, or null while open |
| promised_date | date | Committed delivery date |
| actual_delivery_date | date | Null while in transit |
| promised_lead_time_days | int | order → promised |
| actual_lead_time_days | int | order → actual |
| delay_days | int | promised → actual. Positive is late; null while open |
| is_open | bool | Not yet delivered |
| is_late | bool | Arrived after promised. Null while open |

## quarantine_sales

Sale rows that failed validation, with `quarantine_reason` and `quarantined_at`. Empty on
clean data.

## suppliers_snapshot

dbt snapshot holding Type-2 supplier history. Adds `dbt_valid_from` and `dbt_valid_to`;
the current version has a null `dbt_valid_to`. History starts when snapshotting starts —
dbt stamps the time it first saw a row, not the business `valid_from`.
