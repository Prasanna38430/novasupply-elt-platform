with source as (
    select * from {{ source('raw', 'sales') }}
)

select
    sale_id,
    {{ clean_cast('sale_date', 'date') }}        as sale_date,
    store_id,
    product_id,
    {{ clean_cast('quantity', 'integer') }}      as quantity,
    {{ clean_cast('unit_price_eur', 'double') }} as unit_price_eur,
    {{ clean_cast('discount_pct', 'double') }}   as discount_pct,
    {{ clean_cast('amount_eur', 'double') }}     as amount_eur
from source
