-- Hourly statistics per tag from the long-term archive, good values only.
select
    tag,
    date_trunc('hour', ts_utc)                       as hour_utc,
    min(ts_local)                                    as hour_local_start,
    avg(value)    filter (where quality_flag = 'good') as mean_value,
    min(value)    filter (where quality_flag = 'good') as min_value,
    max(value)    filter (where quality_flag = 'good') as max_value,
    count(*)      filter (where quality_flag = 'good') as n_good,
    count(*)      filter (where quality_flag = 'masked') as n_masked
from {{ ref('fct_reading') }}
where source = 'longterm'
group by 1, 2
