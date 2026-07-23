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

    {{ dbt.datediff('order_date', 'promised_date', 'day') }}        as promised_lead_time_days,
    {{ dbt.datediff('order_date', 'actual_delivery_date', 'day') }} as actual_lead_time_days,

    -- Days past the promised date. Positive means late; null while the order is open.
    {{ dbt.datediff('promised_date', 'actual_delivery_date', 'day') }} as delay_days,

    case
        when actual_delivery_date is null then null
        when actual_delivery_date > promised_date then true
        else false
    end as is_late
from po
