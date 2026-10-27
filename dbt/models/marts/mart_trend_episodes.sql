-- Consecutive flagged days per tag become one trend-deviation episode.
with f as (
    select *,
        date_diff('day', date '2000-01-01', local_date)
          - row_number() over (partition by tag order by local_date) as island
    from {{ ref('mart_trend') }}
    where flag
)

select
    md5(concat_ws('|', tag, cast(min(local_date) as varchar)))   as episode_id,
    tag,
    min(local_date)                                              as start_date,
    max(local_date)                                              as end_date,
    count(*)                                                     as n_days,
    arg_max(deviation, abs(z))                                   as worst_deviation,
    arg_max(baseline, abs(z))                                    as baseline_at_worst,
    max(abs(z))                                                  as max_abs_z,
    min(days_to_spec)                                            as min_days_to_spec
from f
group by tag, island
