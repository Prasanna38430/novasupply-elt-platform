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
├── purchase_orders/dt=YYYY-MM-DD/purchase_orders.csv   daily fact, partitioned by date
└── contracts/                              unstructured: French contract prose
    ├── CTR-2026-NNNN.txt                   master framework contract, one per supplier
    ├── CTR-2026-NNNN-A1.txt                amendment, supersedes clauses of the above
    ├── catalogue.csv                       what each document is, and what it replaces
    └── _ground_truth.csv                   answer key for scoring extraction; the
                                            extraction path never reads it
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
| reliability_score | float | 0-1; higher means more often on time. Drives delivery delays |
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
| discount_pct | float | 0-1 |
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

The star schema analysts and the dashboard query. Five dimensions, four facts, joined on
natural keys, all built by dbt. Everything except the two contract models below was
verified to be identical on DuckDB and Snowflake during the trial; the contract models came
afterwards and have only been built on DuckDB.

> The dbt schema files under `dbt/models/` are the source of truth for these columns: they
> carry the descriptions *and* the tests that enforce them, and `dbt docs generate` renders
> them with the lineage graph. This section repeats them so the marts can be read on GitHub
> without running anything. If the two ever disagree, the schema files win.

## dim_suppliers

| Column | Type | Notes |
|---|---|---|
| supplier_id | string | Primary key |
| supplier_name | string | |
| country, city | string | |
| nominal_lead_time_days | int | Contracted order-to-delivery days |
| reliability_score | float | 0-1; higher means more deliveries on time |
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

Grain: one row per sale line, store × SKU × day. Materialised incrementally on
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
| below_reorder_point | bool | Often true while a delivery is in flight, not itself a problem |
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

## dim_supplier_contracts

The commercial terms in force per supplier today, read out of the contract prose by a
model rather than entered by hand, so treat them as extracted rather than authoritative.
One row per supplier. Where an amendment exists its delivery and penalty clauses win and
every other term still comes from the master contract, so no single document holds this
row.

| Column | Type | Notes |
|---|---|---|
| supplier_id | string | Primary key |
| contract_id | string | The master contract the terms start from |
| amendment_id | string | The amendment, when there is one; else null |
| is_amended | bool | Whether an amendment restated the delivery or penalty clause |
| terms_effective_from | date | When the terms below started applying |
| contracted_lead_time_days | int | Delivery window the supplier committed to |
| penalty_rate_pct_per_day | double | Late penalty, percent of order value per day |
| penalty_cap_pct | int | Ceiling on cumulative penalty, percent of order value |
| min_order_qty | int | Minimum order quantity per reference |
| payment_terms_days | int | Days to pay an invoice |
| quality_tolerance_pct | double | Tolerated non-conformity rate |
| notice_period_days | int | Termination notice |

## fct_contract_compliance

One row per **delivered** purchase order, judged against the contract in force on the day
it was placed. Open orders are excluded, having missed nothing yet.

The two lateness flags answer different questions and routinely disagree: an order can hit
the date promised on it while still exceeding what the framework contract allows.

| Column | Type | Notes |
|---|---|---|
| po_id | string | Primary key. Unique here as well as in `fct_purchase_orders`, which is what proves the term-period join matched exactly one period |
| order_date | date | Determines which contract terms apply |
| supplier_id | string | FK to `dim_suppliers` |
| product_id | string | FK to `dim_products` |
| store_id | string | FK to `dim_stores` |
| governing_document_id | string | The contract or amendment that governed this order |
| governed_by_amendment | bool | Whether that document was an amendment |
| ordered_qty | int | |
| order_value_eur | double | Ordered quantity at unit cost; the base the penalty is charged on |
| contracted_lead_time_days | int | From the terms in force at `order_date` |
| actual_lead_time_days | int | order → actual delivery |
| days_over_contract | int | Days beyond the contracted window; zero when in time |
| is_contract_breach | bool | Exceeded the framework contract. The commercial question |
| is_late_vs_promise | bool | Missed the date promised on this order. The operational one |
| days_late_vs_promise | int | Days past the promised date |
| penalty_rate_pct_per_day | double | From the terms in force |
| penalty_cap_pct | int | From the terms in force |
| penalty_eur | double | Accrues per day over the window, capped at the contract's ceiling |

## quarantine_sales

Sale rows that failed validation, with `quarantine_reason` and `quarantined_at`. Empty on
clean data.

## suppliers_snapshot

dbt snapshot holding Type-2 supplier history. Adds `dbt_valid_from` and `dbt_valid_to`;
the current version has a null `dbt_valid_to`. History starts when snapshotting starts,
dbt stamps the time it first saw a row, not the business `valid_from`.
