with po as (
    select * from {{ ref('stg_purchase_orders') }}
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

    actual_delivery_date is null as is_open,

    date_diff('day', order_date, promised_date)          as promised_lead_time_days,
    date_diff('day', order_date, actual_delivery_date)   as actual_lead_time_days,

    -- Days past the promised date. Positive means late; null while the order is open.
    date_diff('day', promised_date, actual_delivery_date) as delay_days,

    case
        when actual_delivery_date is null then null
        when actual_delivery_date > promised_date then true
        else false
    end as is_late
from po
