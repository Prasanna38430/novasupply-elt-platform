with source as (
    select * from {{ source('raw', 'suppliers') }}
)

select
    supplier_id,
    supplier_name,
    country,
    city,
    cast(nominal_lead_time_days as integer) as nominal_lead_time_days,
    cast(reliability_score as double)       as reliability_score,
    cast(valid_from as date)                as valid_from
from source
