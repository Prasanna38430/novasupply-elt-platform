-- Revenue must reconcile to its own components. A cent of tolerance covers floating
-- point rounding; anything larger means quantity, price or discount has drifted.
select sale_id
from {{ ref('fct_sales') }}
where abs(amount_eur - (quantity * unit_price_eur * (1 - discount_pct))) > 0.01
