with source as (
    select * from {{ source('raw', 'products') }}
)

select
    product_id,
    product_name,
    category,
    supplier_id,
    cast(unit_cost_eur as double)  as unit_cost_eur,
    cast(unit_price_eur as double) as unit_price_eur
from source
