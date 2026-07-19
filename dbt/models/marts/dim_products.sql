with products as (
    select * from {{ ref('stg_products') }}
)

select
    product_id,
    product_name,
    category,
    supplier_id,
    unit_cost_eur,
    unit_price_eur,
    round(unit_price_eur - unit_cost_eur, 2)                          as unit_margin_eur,
    round((unit_price_eur - unit_cost_eur) / nullif(unit_price_eur, 0), 3) as margin_pct
from products
