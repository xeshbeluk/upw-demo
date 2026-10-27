-- Episodes in which a tag was beyond a spec or alert limit (long-term archive, good values only).
-- Consecutive 5-minute readings beyond the same limit form one episode; episodes less than
-- 4 hours apart are merged (a value hovering at the limit is one event, not hundreds).
-- maintenance_related = the episode started during or shortly after a maintenance event whose
-- type affects this tag (event_types.default_tags), e.g. particles after a filter change.
-- Such episodes are reported separately, not hidden.
with beyond as (
    select
        r.tag, r.ts_utc, r.ts_local, r.value,
        l.limit_type, l.limit_value, l.severity
    from {{ ref('fct_reading') }} r
    join {{ ref('spec_limits') }} l
        on l.tag = r.tag and cast(r.ts_local as date) >= l.valid_from
    where r.source = 'longterm' and r.quality_flag = 'good'
      and ((l.limit_type = 'max' and r.value > l.limit_value)
        or (l.limit_type = 'min' and r.value < l.limit_value))
),

gaps as (
    select *,
        case when ts_utc - lag(ts_utc) over w > interval 4 hour or lag(ts_utc) over w is null
             then 1 else 0 end as new_episode
    from beyond
    window w as (partition by tag, limit_type, severity order by ts_utc)
),

islands as (
    select *, sum(new_episode) over (partition by tag, limit_type, severity order by ts_utc
                                     rows unbounded preceding) as island
    from gaps
),

episodes as (
    select
        tag, limit_type, limit_value, severity,
        min(ts_utc)                         as start_utc,
        max(ts_utc) + interval 5 minute     as end_utc,
        min(ts_local)                       as start_local,
        count(*) * 5                        as minutes_beyond,
        date_diff('minute', min(ts_utc), max(ts_utc)) + 5 as duration_min,
        case when limit_type = 'max' then max(value) else min(value) end as peak_value
    from islands
    group by tag, limit_type, limit_value, severity, island
)

select
    md5(concat_ws('|', e.tag, e.severity, e.limit_type, cast(e.start_utc as varchar))) as episode_id,
    e.*,
    t.description,
    t.unit,
    m.event_id                         as related_event_id,
    m.event_label                      as related_event,
    m.event_id is not null             as maintenance_related
from episodes e
join {{ ref('tags') }} t using (tag)
left join lateral (
    select ev.event_id, ev.event_label
    from {{ ref('dim_event') }} ev
    where ev.is_maintenance
      and contains('|' || ev.default_tags || '|', '|' || e.tag || '|')
      and e.start_utc between ev.ts_utc - interval 1 hour
                          and ev.ts_utc + to_seconds(cast(ev.window_after_h * 3600 as bigint))
    order by ev.ts_utc desc
    limit 1
) m on true
