-- Sale rows that failed validation, kept with the reason they failed so someone can
-- actually investigate. The alternative -- dropping them silently -- is how data teams
-- lose trust; the other alternative -- letting them through -- is how dashboards lie.
select
    *,
    case
        when sale_date is null     then 'missing or unparseable sale_date'
        when store_id is null      then 'missing store_id'
        when product_id is null    then 'missing product_id'
        when quantity is null      then 'missing or unparseable quantity'
        when quantity <= 0         then 'non-positive quantity'
        when amount_eur is null    then 'missing or unparseable amount_eur'
        when amount_eur < 0        then 'negative amount_eur'
        when discount_pct is null  then 'missing or unparseable discount_pct'
        else 'discount_pct outside 0-1'
    end as quarantine_reason,
    now() as quarantined_at
from {{ ref('stg_sales__typed') }}
where not ({{ sales_row_is_valid() }})
