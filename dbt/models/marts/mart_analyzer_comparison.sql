-- Analyser study: TOC analyser A vs B at the same point of use, paired 5-minute values
-- (both good). Daily mean difference and ratio; the app adds a Bland-Altman view.
with a as (select ts_utc, ts_local, value from {{ ref('fct_reading') }}
           where tag = 'UPW1.POU.TOC' and source = 'longterm' and quality_flag = 'good'),
     b as (select ts_utc, value from {{ ref('fct_reading') }}
           where tag = 'UPW1.POU.TOC_B' and source = 'longterm' and quality_flag = 'good')

select
    cast(a.ts_local as date)             as local_date,
    count(*)                             as n_pairs,
    avg(a.value)                         as mean_a,
    avg(b.value)                         as mean_b,
    avg(b.value - a.value)               as mean_diff,
    stddev_samp(b.value - a.value)       as sd_diff,
    avg(b.value / nullif(a.value, 0))    as mean_ratio
from a join b using (ts_utc)
group by 1
