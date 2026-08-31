-- fct_contract_compliance reaches its terms through a range join on the order date, and a
-- range join fails quietly: an order falling in a gap between validity periods is dropped
-- rather than flagged, and the penalty exposure simply comes out too low. Row counts have
-- to match, so every delivered order is accounted for.
select po.po_id
from {{ ref('fct_purchase_orders') }} po
left join {{ ref('fct_contract_compliance') }} c on c.po_id = po.po_id
where po.is_open = false
  and c.po_id is null
