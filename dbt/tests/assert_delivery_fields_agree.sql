-- A purchase order is either delivered or it isn't. Having a delivery date with no
-- received quantity (or the reverse) means the load dropped one of the two fields.
select po_id
from {{ ref('fct_purchase_orders') }}
where (actual_delivery_date is not null and received_qty is null)
   or (actual_delivery_date is null and received_qty is not null)
