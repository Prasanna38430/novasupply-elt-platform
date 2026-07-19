with source as (
    select * from {{ source('raw', 'products') }}
)

select
    product_id,
    product_name,
    category,
    supplier_id,
    {{ clean_cast('unit_cost_eur', 'double') }}  as unit_cost_eur,
    {{ clean_cast('unit_price_eur', 'double') }} as unit_price_eur
from source
