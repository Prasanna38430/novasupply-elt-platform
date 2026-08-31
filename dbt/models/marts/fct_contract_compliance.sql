-- Every delivered order judged against the contract that governed it when it was placed.
--
-- This is the join the platform existed to make impossible until now: what a supplier
-- committed to lives in prose, what they actually did lives in the orders, and neither
-- half means much alone. Extracting the first into columns is what lets them meet.
--
-- Two different notions of "late" sit side by side here on purpose:
--
--   is_late_vs_promise  - the delivery missed the date promised on that specific order,
--                         which is the operational question the warehouse already answered
--   is_contract_breach  - the delivery took longer than the framework contract allows,
--                         which is the commercial question, and the one with money on it
--
-- They disagree whenever an order was promised a date the contract would not have
-- permitted, so keeping both is what makes the gap visible rather than averaging it away.
with orders as (
    select * from {{ ref('fct_purchase_orders') }}
),

products as (
    select * from {{ ref('dim_products') }}
),

terms as (
    select * from {{ ref('int_contracts__terms_history') }}
),

delivered as (
    -- An open order has not missed anything yet; lead time and delay are null on it.
    select * from orders where is_open = false
),

joined as (
    select
        d.po_id,
        d.order_date,
        d.supplier_id,
        d.product_id,
        d.store_id,
        d.ordered_qty,
        d.actual_lead_time_days,
        d.delay_days,
        d.is_late,
        p.unit_cost_eur,
        t.governing_document_id,
        t.is_amended,
        t.contracted_lead_time_days,
        t.penalty_rate_pct_per_day,
        t.penalty_cap_pct
    from delivered d
    join products p on p.product_id = d.product_id
    -- The period that was in force on the order date. valid_to is exclusive, so an order
    -- placed on the day an amendment takes effect falls under the amendment.
    join terms t
        on  t.supplier_id = d.supplier_id
        and d.order_date >= t.valid_from
        and d.order_date <  t.valid_to
),

measured as (
    select
        *,
        round(ordered_qty * unit_cost_eur, 2) as order_value_eur,
        greatest(actual_lead_time_days - contracted_lead_time_days, 0) as days_over_contract
    from joined
)

select
    po_id,
    order_date,
    supplier_id,
    product_id,
    store_id,
    governing_document_id,
    is_amended                      as governed_by_amendment,
    ordered_qty,
    order_value_eur,

    contracted_lead_time_days,
    actual_lead_time_days,
    days_over_contract,
    days_over_contract > 0          as is_contract_breach,
    is_late                         as is_late_vs_promise,
    delay_days                      as days_late_vs_promise,

    penalty_rate_pct_per_day,
    penalty_cap_pct,
    -- Penalty accrues per day over the contracted window and stops at the cap, exactly as
    -- article 3 words it. Zero when nothing was late, since days_over_contract is zero.
    round(
        least(
            order_value_eur * penalty_rate_pct_per_day / 100.0 * days_over_contract,
            order_value_eur * penalty_cap_pct / 100.0
        ), 2
    )                               as penalty_eur
from measured
