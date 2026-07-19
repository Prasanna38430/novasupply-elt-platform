with source as (
    select * from {{ source('raw', 'purchase_orders') }}
)

select
    po_id,
    cast(order_date as date)    as order_date,
    supplier_id,
    product_id,
    store_id,
    cast(ordered_qty as integer) as ordered_qty,
    cast(promised_date as date)  as promised_date,
    -- Open orders arrive as empty strings in RAW; make them proper NULLs before casting.
    cast(nullif(actual_delivery_date, '') as date)  as actual_delivery_date,
    cast(nullif(received_qty, '') as integer)       as received_qty
from source
