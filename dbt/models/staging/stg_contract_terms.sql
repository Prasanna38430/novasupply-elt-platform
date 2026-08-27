-- Terms a model read out of the contract prose, arriving as a seed rather than through
-- the raw zone: extraction needs a local LLM, which CI does not have, so the result is a
-- reviewed artefact in version control and the model reruns only when the contracts do.
-- See ingestion/extract_contract_terms.py.
with source as (
    select * from {{ ref('contract_terms') }}
)

select
    document_id,
    supplier_id,
    lead_time         as contracted_lead_time_days,
    penalty_rate      as penalty_rate_pct_per_day,
    penalty_cap       as penalty_cap_pct,
    min_order_qty,
    payment_terms     as payment_terms_days,
    quality_tolerance as quality_tolerance_pct,
    notice_period     as notice_period_days
from source
