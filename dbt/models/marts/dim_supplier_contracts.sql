-- The commercial terms in force per supplier today.
--
-- The open period out of the term history: whichever document governs now, with the
-- clauses an amendment left alone still coming from the master contract. Deriving it from
-- the history rather than rebuilding the same coalesce keeps one definition of what "in
-- force" means, shared with fct_contract_compliance.
with periods as (
    select * from {{ ref('int_contracts__terms_history') }}
)

select
    supplier_id,
    contract_id,
    amendment_id,
    is_amended,
    valid_from as terms_effective_from,
    contracted_lead_time_days,
    penalty_rate_pct_per_day,
    penalty_cap_pct,
    min_order_qty,
    payment_terms_days,
    quality_tolerance_pct,
    notice_period_days
from periods
where valid_to = date '9999-12-31'
