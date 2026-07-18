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
