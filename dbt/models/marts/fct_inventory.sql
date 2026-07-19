with stock as (
    select * from {{ ref('int_inventory__stock_status') }}
)

select
    snapshot_date,
    store_id,
    product_id,
    on_hand_qty,
    reorder_point,
    in_transit_qty,
    avg_daily_units,
    is_stockout,
    below_reorder_point,
    days_of_cover
from stock
