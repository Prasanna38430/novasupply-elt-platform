-- The commercial terms in force per supplier, once amendments are applied.
--
-- An amendment restates only the clauses it changes, so the terms actually governing a
-- supplier are not in any single document: the delivery window and penalty come from the
-- amendment where one exists, and everything it stayed silent about still comes from the
-- master contract. Resolving that here means nothing downstream has to know amendments
-- exist.
with catalogue as (
    select * from {{ ref('stg_contract_catalogue') }}
),

terms as (
    select * from {{ ref('stg_contract_terms') }}
),

contracts as (
    select
        c.supplier_id,
        c.document_id,
        c.effective_date,
        t.contracted_lead_time_days,
        t.penalty_rate_pct_per_day,
        t.penalty_cap_pct,
        t.min_order_qty,
        t.payment_terms_days,
        t.quality_tolerance_pct,
        t.notice_period_days
    from catalogue c
    join terms t on t.document_id = c.document_id
    where c.document_type = 'contrat_cadre'
),

amendments as (
    select
        c.supersedes as amends_document_id,
        c.document_id,
        c.effective_date,
        t.contracted_lead_time_days,
        t.penalty_rate_pct_per_day,
        t.penalty_cap_pct
    from catalogue c
    join terms t on t.document_id = c.document_id
    where c.document_type = 'avenant'
)

select
    c.supplier_id,
    c.document_id                                        as contract_id,
    a.document_id                                        as amendment_id,
    a.document_id is not null                            as is_amended,
    -- The date the terms below started applying, which is the amendment's where there is
    -- one; useful later for judging an order against the terms in force when it was placed.
    coalesce(a.effective_date, c.effective_date)         as terms_effective_from,

    -- Restated by an amendment when there is one.
    coalesce(a.contracted_lead_time_days,
             c.contracted_lead_time_days)                as contracted_lead_time_days,
    coalesce(a.penalty_rate_pct_per_day,
             c.penalty_rate_pct_per_day)                 as penalty_rate_pct_per_day,
    coalesce(a.penalty_cap_pct, c.penalty_cap_pct)       as penalty_cap_pct,

    -- Never restated, so always the master contract's.
    c.min_order_qty,
    c.payment_terms_days,
    c.quality_tolerance_pct,
    c.notice_period_days
from contracts c
left join amendments a on a.amends_document_id = c.document_id
