with source as (
    select * from {{ source('raw', 'inventory_snapshots') }}
)

select
    cast(snapshot_date as date)     as snapshot_date,
    store_id,
    product_id,
    cast(on_hand_qty as integer)    as on_hand_qty,
    cast(reorder_point as integer)  as reorder_point,
    cast(in_transit_qty as integer) as in_transit_qty
from source
