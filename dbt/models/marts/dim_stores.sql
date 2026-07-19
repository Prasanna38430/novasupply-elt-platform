with stores as (
    select * from {{ ref('stg_stores') }}
)

select
    store_id,
    store_name,
    city,
    region
from stores
