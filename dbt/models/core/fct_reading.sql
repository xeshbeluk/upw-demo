-- Every process value from both export folders, with a quality flag.
--   masked  = inside an analyser calibration / maintenance / fault period (see int_mask_periods)
-- Rows of tags that are not in the tag catalogue stay out (see quality.qa_unknown_tags).
with r as (
    select *
    from {{ ref('stg_readings') }}
    where parse_status = 'ok'
      and tag in (select tag from {{ ref('tags') }})
),

flagged as (
    select
        r.source, r.tag, r.ts_utc, r.ts_local, r.value_num as value, r.resolution_s, r.dst_repeat,
        m.reason as mask_reason, r.source_file,
        row_number() over (partition by r.source, r.tag, r.ts_utc order by m.reason nulls last, r.source_file desc) as rn
    from r
    left join {{ ref('int_mask_periods') }} m
        on m.tag = r.tag and r.ts_utc >= m.start_utc and r.ts_utc < m.end_utc
)

select
    source,                              -- longterm (5 min) | maintenance (10 s)
    tag,
    ts_utc,
    ts_local,
    value,
    resolution_s,
    case when mask_reason is null then 'good' else 'masked' end as quality_flag,
    mask_reason,
    dst_repeat,
    source_file
from flagged
where rn = 1
