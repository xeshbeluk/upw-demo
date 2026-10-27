-- Where both folders cover the same tag and time: compare the 10-s maintenance data, averaged
-- to 5 minutes, with the long-term archive. Large differences point to an export problem.
with m as (
    select tag, time_bucket(interval 5 minute, ts_utc) as ts_utc, avg(value) as mt_value, count(*) as n
    from {{ ref('fct_reading') }} where source = 'maintenance' and quality_flag = 'good' group by 1, 2
),
l as (
    select tag, ts_utc, value as lt_value from {{ ref('fct_reading') }}
    where source = 'longterm' and quality_flag = 'good'
)
select m.tag, count(*) as n_overlapping_5min, avg(abs(m.mt_value - l.lt_value)) as mean_abs_diff,
       max(abs(m.mt_value - l.lt_value)) as max_abs_diff
from m join l using (tag, ts_utc)
group by 1
order by 1
