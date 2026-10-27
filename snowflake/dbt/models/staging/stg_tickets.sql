-- One row per ticket: valid ids and priorities only, newest load wins on duplicates.
select
    ticket_id,
    lower(trim(requester)) as requester,
    category,
    priority,
    status,
    created_at,
    resolved_at,
    summary
from {{ source('raw', 'tickets') }}
where regexp_like(ticket_id, 'INC-[0-9]+')
  and priority in ('P1', 'P2', 'P3', 'P4')
  and created_at is not null
qualify row_number() over (partition by ticket_id order by ingested_at desc) = 1
