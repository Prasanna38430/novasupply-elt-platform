-- is_late is derived from the two dates, so it must always agree with them. This guards
-- the supplier-performance numbers, which the whole platform is judged on.
select po_id
from {{ ref('fct_purchase_orders') }}
where actual_delivery_date is not null
  and is_late <> (actual_delivery_date > promised_date)
