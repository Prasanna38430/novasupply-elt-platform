with source as (
    select * from {{ source('raw', 'sales') }}
)

select
    sale_id,
    cast(sale_date as date)        as sale_date,
    store_id,
    product_id,
    cast(quantity as integer)      as quantity,
    cast(unit_price_eur as double) as unit_price_eur,
    cast(discount_pct as double)   as discount_pct,
    cast(amount_eur as double)     as amount_eur
from source
