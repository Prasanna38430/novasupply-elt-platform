{{
    config(
        materialized='incremental',
        unique_key='sale_id',
        incremental_strategy='delete+insert'
    )
}}

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

{% if is_incremental() %}
-- Reprocess only the latest loaded day onward. delete+insert on sale_id makes this
-- idempotent, so re-running a day that arrived in pieces can't duplicate rows.
where sale_date >= (select max(sale_date) from {{ this }})
{% endif %}
