{{
    config(
        enabled = (target.type == 'snowflake'),
        secure = true,
        materialized = 'view'
    )
}}

-- Role-aware view of the supplier dimension.
--
-- Snowflake's Dynamic Data Masking would normally do this by attaching a masking policy
-- to the column, but that is an Enterprise Edition feature and this account is Standard.
-- A secure view reaches the same outcome on any edition: the sensitive columns are
-- resolved against current_role() at query time, so the data returned depends on who is
-- asking rather than on which copy of the table they found.
--
-- "Secure" is not decoration. An ordinary view can leak the rows it filtered out through
-- query plans and error messages; a secure view blocks those side channels, at the cost
-- of some optimisation. That trade is obviously right when the filtering is the point.
--
-- Disabled on DuckDB, which has neither roles nor secure views. See ADR 0006.

with suppliers as (
    select * from {{ ref('dim_suppliers') }}
)

select
    supplier_id,

    case
        when current_role() in ('ACCOUNTADMIN', 'NOVASUPPLY_TRANSFORMER', 'NOVASUPPLY_LOADER')
            then supplier_name
        else '*** RESTRICTED ***'
    end as supplier_name,

    country,
    city,
    nominal_lead_time_days,

    -- Nulled rather than zeroed for unprivileged roles: a fake 0 would quietly corrupt
    -- any average an analyst ran over this column.
    case
        when current_role() in ('ACCOUNTADMIN', 'NOVASUPPLY_TRANSFORMER', 'NOVASUPPLY_LOADER')
            then reliability_score
        else null
    end as reliability_score,

    -- The banded tier stays visible: it is what analysts actually need for reporting,
    -- without exposing the underlying commercial terms.
    reliability_tier,
    valid_from
from suppliers
