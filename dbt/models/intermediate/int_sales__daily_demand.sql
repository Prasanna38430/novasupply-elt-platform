-- Average daily demand per store and SKU over the trailing 28 days, used to project how
-- long current stock will last. A shortish window keeps the rate responsive to recent
-- trends rather than the whole 90-day history.
with sales as (
    select * from {{ ref('stg_sales') }}
),

bounds as (
    select max(sale_date) as max_date from sales
)

select
    s.store_id,
    s.product_id,
    sum(s.quantity)         as units_last_28d,
    sum(s.quantity) / 28.0  as avg_daily_units
from sales s
cross join bounds b
where date_diff('day', s.sale_date, b.max_date) < 28
group by s.store_id, s.product_id
