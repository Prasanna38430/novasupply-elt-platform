-- Calendar spine covering the full range of the inventory history, one row per day.
-- Having a real date dimension means the dashboard can group by month, week or weekday
-- without repeating date functions everywhere.
with spine as (
    select cast(g as date) as date_day
    from generate_series(
        (select min(snapshot_date) from {{ ref('stg_inventory_snapshots') }})::timestamp,
        (select max(snapshot_date) from {{ ref('stg_inventory_snapshots') }})::timestamp,
        interval 1 day
    ) as t(g)
)

select
    date_day,
    extract(year  from date_day)  as year,
    extract(month from date_day)  as month,
    extract(day   from date_day)  as day_of_month,
    extract(isodow from date_day) as iso_day_of_week,   -- 1 = Monday, 7 = Sunday
    strftime(date_day, '%A')      as weekday_name,
    extract(week from date_day)   as iso_week,
    extract(isodow from date_day) >= 6 as is_weekend
from spine
order by date_day
