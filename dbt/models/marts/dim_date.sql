-- Calendar spine, one row per day covering the loaded history.
--
-- Built from the distinct snapshot dates rather than a generated series: the inventory
-- fact already has exactly one row per store, SKU and day, so its dates are precisely
-- the period we hold data for. It also avoids generate_series, which DuckDB and
-- Snowflake spell differently.
with days as (
    select distinct snapshot_date as date_day
    from {{ ref('stg_inventory_snapshots') }}
)

select
    date_day,
    extract(year  from date_day) as year,
    extract(month from date_day) as month,
    extract(day   from date_day) as day_of_month,

    {{ iso_day_of_week('date_day') }} as iso_day_of_week,   -- 1 = Monday, 7 = Sunday
    {{ iso_week('date_day') }}        as iso_week,

    case {{ iso_day_of_week('date_day') }}
        when 1 then 'Monday'
        when 2 then 'Tuesday'
        when 3 then 'Wednesday'
        when 4 then 'Thursday'
        when 5 then 'Friday'
        when 6 then 'Saturday'
        else 'Sunday'
    end as weekday_name,

    {{ iso_day_of_week('date_day') }} >= 6 as is_weekend
from days
