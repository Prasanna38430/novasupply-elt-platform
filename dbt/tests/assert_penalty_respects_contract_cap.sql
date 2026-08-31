-- Article 3 caps the cumulative penalty at a share of the order value. A penalty above
-- that ceiling would be a number the contract does not permit, so it is worth failing the
-- build over rather than discovering it in a supplier negotiation. The tolerance absorbs
-- rounding to the cent, nothing more.
select po_id
from {{ ref('fct_contract_compliance') }}
where penalty_eur > (order_value_eur * penalty_cap_pct / 100.0) + 0.01
