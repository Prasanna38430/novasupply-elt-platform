with source as (
    select * from {{ source('raw', 'contract_catalogue') }}
)

select
    document_id,
    supplier_id,
    document_type,
    -- Null on a master contract; on an amendment, the contract it modifies.
    nullif(trim(supersedes), '')            as supersedes,
    {{ clean_cast('effective_date', 'date') }} as effective_date,
    file_name
from source
