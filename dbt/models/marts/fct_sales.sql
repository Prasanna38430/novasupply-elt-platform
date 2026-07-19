with sales as (
    select * from {{ ref('stg_sales') }}
)

select
    sale_id,          -- degenerate dimension: the transaction id lives on the fact
    sale_date,
    store_id,
    product_id,
    quantity,
    unit_price_eur,
    discount_pct,
    amount_eur
from sales
