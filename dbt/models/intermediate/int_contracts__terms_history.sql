-- Contract terms as periods, not as a single current state.
--
-- Amendments land part-way through the history, so an order placed in April has to be
-- judged against the window that existed in April rather than the tighter one negotiated
-- in June. Collapsing straight to current terms would quietly re-judge months of past
-- deliveries against a promise nobody had made yet, and would manufacture breaches that
-- never happened.
--
-- One row per supplier per validity window: the master contract governs until an
-- amendment lands, the amendment governs from then on. `valid_to` is exclusive, and open
-- periods carry the usual far-future sentinel so a between-style join needs no null
-- handling.
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
        c.supplier_id,
        c.document_id,
        c.supersedes as amends_document_id,
        c.effective_date,
        t.contracted_lead_time_days,
        t.penalty_rate_pct_per_day,
        t.penalty_cap_pct
    from catalogue c
    join terms t on t.document_id = c.document_id
    where c.document_type = 'avenant'
),

periods as (
    select
        c.supplier_id,
        c.document_id                                  as contract_id,
        cast(null as {{ dbt.type_string() }})          as amendment_id,
        c.document_id                                  as governing_document_id,
        false                                          as is_amended,
        c.effective_date                               as valid_from,
        coalesce(a.effective_date, date '9999-12-31')  as valid_to,
        c.contracted_lead_time_days,
        c.penalty_rate_pct_per_day,
        c.penalty_cap_pct,
        c.min_order_qty,
        c.payment_terms_days,
        c.quality_tolerance_pct,
        c.notice_period_days
    from contracts c
    left join amendments a on a.amends_document_id = c.document_id

    union all

    -- The amendment restates the delivery and penalty clauses and nothing else, so every
    -- other term carries forward from the contract it modifies.
    select
        a.supplier_id,
        c.document_id                as contract_id,
        a.document_id                as amendment_id,
        a.document_id                as governing_document_id,
        true                         as is_amended,
        a.effective_date             as valid_from,
        date '9999-12-31'            as valid_to,
        a.contracted_lead_time_days,
        a.penalty_rate_pct_per_day,
        a.penalty_cap_pct,
        c.min_order_qty,
        c.payment_terms_days,
        c.quality_tolerance_pct,
        c.notice_period_days
    from amendments a
    join contracts c on c.document_id = a.amends_document_id
)

select * from periods
