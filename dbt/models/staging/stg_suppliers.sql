with source as (
    select * from {{ source('raw', 'suppliers') }}
)

select
    supplier_id,
    supplier_name,
    country,
    city,
    {{ clean_cast('nominal_lead_time_days', 'integer') }} as nominal_lead_time_days,
    {{ clean_cast('reliability_score', 'double') }}       as reliability_score,
    {{ clean_cast('valid_from', 'date') }}                as valid_from
from source
