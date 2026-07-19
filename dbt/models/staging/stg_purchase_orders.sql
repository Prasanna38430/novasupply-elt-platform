with source as (
    select * from {{ source('raw', 'purchase_orders') }}
)

select
    po_id,
    {{ clean_cast('order_date', 'date') }}            as order_date,
    supplier_id,
    product_id,
    store_id,
    {{ clean_cast('ordered_qty', 'integer') }}        as ordered_qty,
    {{ clean_cast('promised_date', 'date') }}         as promised_date,
    -- Open orders arrive blank in RAW; clean_cast turns those into proper NULLs.
    {{ clean_cast('actual_delivery_date', 'date') }}  as actual_delivery_date,
    {{ clean_cast('received_qty', 'integer') }}       as received_qty
from source
