with suppliers as (
    select * from {{ ref('stg_suppliers') }}
)

select
    supplier_id,
    supplier_name,
    country,
    city,
    nominal_lead_time_days,
    reliability_score,
    -- Banded reliability, handy for grouping suppliers in the dashboard.
    case
        when reliability_score >= 0.95 then 'High'
        when reliability_score >= 0.85 then 'Medium'
        else 'Low'
    end as reliability_tier,
    valid_from
from suppliers
