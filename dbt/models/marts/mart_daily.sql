-- Daily statistics per tag on the plant's local calendar day, good long-term values only.
-- completeness = good readings / 288 expected 5-minute readings.
select
    tag,
    cast(ts_local as date)                                        as local_date,
    avg(value)                    filter (where quality_flag = 'good') as mean_value,
    median(value)                 filter (where quality_flag = 'good') as median_value,
    min(value)                    filter (where quality_flag = 'good') as min_value,
    max(value)                    filter (where quality_flag = 'good') as max_value,
    quantile_cont(value, 0.05)    filter (where quality_flag = 'good') as p05_value,
    quantile_cont(value, 0.95)    filter (where quality_flag = 'good') as p95_value,
    count(*)                      filter (where quality_flag = 'good') as n_good,
    count(*)                      filter (where quality_flag = 'masked') as n_masked,
    least(count(*) filter (where quality_flag = 'good') / 288.0, 1.0)  as completeness
from {{ ref('fct_reading') }}
where source = 'longterm'
group by 1, 2
