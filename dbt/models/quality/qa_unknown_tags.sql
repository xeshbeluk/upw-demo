-- Columns in the exports that are not in the tag catalogue (kept in landing, not used).
select tag, source, count(*) as n_values, min(ts_local) as first_seen, max(ts_local) as last_seen,
       min(source_file) as example_file
from {{ ref('stg_readings') }}
where tag not in (select tag from {{ ref('tags') }})
group by all
