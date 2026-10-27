-- Same definition as the PySpark gold table `gold_ticket_stats`.
select
    category,
    priority,
    count(*) as tickets,
    round(avg(datediff('second', created_at, resolved_at) / 3600.0), 2) as avg_resolution_hours,
    count_if(status in ('open', 'in_progress')) as open_tickets
from {{ ref('stg_tickets') }}
group by category, priority
order by category, priority
