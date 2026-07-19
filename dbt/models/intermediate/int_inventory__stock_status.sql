with inventory as (
    select * from {{ ref('stg_inventory_snapshots') }}
),

demand as (
    select * from {{ ref('int_sales__daily_demand') }}
)

select
    inventory.snapshot_date,
    inventory.store_id,
    inventory.product_id,
    inventory.on_hand_qty,
    inventory.reorder_point,
    inventory.in_transit_qty,
    coalesce(demand.avg_daily_units, 0) as avg_daily_units,

    inventory.on_hand_qty = 0                        as is_stockout,
    inventory.on_hand_qty <= inventory.reorder_point as below_reorder_point,

    -- How many days the current stock lasts at the recent demand rate. Null when there
    -- is no recent demand to divide by, since cover is undefined then.
    case
        when coalesce(demand.avg_daily_units, 0) = 0 then null
        else round(inventory.on_hand_qty / demand.avg_daily_units, 1)
    end as days_of_cover
from inventory
left join demand
    on  inventory.store_id   = demand.store_id
    and inventory.product_id = demand.product_id
