-- Valid sale rows only. Anything failing the rule is diverted to quarantine_sales, so a
-- handful of malformed rows degrades the numbers slightly instead of failing the run.
select *
from {{ ref('stg_sales__typed') }}
where {{ sales_row_is_valid() }}
