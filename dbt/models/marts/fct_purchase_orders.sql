with po as (
    select * from {{ ref('int_purchase_orders__delays') }}
)

select
    po_id,
    order_date,
    supplier_id,
    product_id,
    store_id,
    ordered_qty,
    received_qty,
    promised_date,
    actual_delivery_date,
    promised_lead_time_days,
    actual_lead_time_days,
    delay_days,
    is_open,
    is_late
from po
