{{ config(materialized='ephemeral') }}

-- Typed but unfiltered sales. Ephemeral, so it compiles into a CTE inside the models
-- below rather than creating a relation of its own. Both stg_sales and quarantine_sales
-- read from here, which is what keeps their casting identical.
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
