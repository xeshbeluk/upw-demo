select source, tag, ts_utc, count(*) from {{ ref('fct_reading') }} group by 1, 2, 3 having count(*) > 1
