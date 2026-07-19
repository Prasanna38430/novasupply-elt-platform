with source as (
    select * from {{ source('raw', 'inventory_snapshots') }}
)

select
    {{ clean_cast('snapshot_date', 'date') }}     as snapshot_date,
    store_id,
    product_id,
    {{ clean_cast('on_hand_qty', 'integer') }}    as on_hand_qty,
    {{ clean_cast('reorder_point', 'integer') }}  as reorder_point,
    {{ clean_cast('in_transit_qty', 'integer') }} as in_transit_qty
from source
