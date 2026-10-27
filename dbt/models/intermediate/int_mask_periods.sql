-- Periods in which an analyser's values must not be used:
--   (1) the analyser itself reported a non-OK status (calibration, maintenance, fault)
--   (2) the diary records a calibration for that analyser - catches calibrations where the
--       operator forgot to set the status (the values then look like a real excursion)
with s as (
    select
        tag, ts_utc, status_code,
        epoch(ts_utc) / 300 - row_number() over (partition by tag, status_code order by ts_utc) as island
    from {{ ref('stg_analyzer_status') }}
    where status_code > 0
),

status_periods as (
    select
        tag,
        min(ts_utc)                          as start_utc,
        max(ts_utc) + interval 5 minute      as end_utc,
        case any_value(status_code) when 1 then 'status: calibration' when 2 then 'status: maintenance'
             when 3 then 'status: fault' else 'status: ' || any_value(status_code) end as reason
    from s
    group by tag, status_code, island
),

cal_events as (
    select e.event_id, e.ts_utc, e.unit_id, e.activity, et.mask_hours
    from {{ ref('int_events') }} e
    join {{ ref('event_types') }} et on et.event_type = e.event_type
    where e.resolution_status = 'ok' and et.masks_analyzers
),

named as (            -- analyser parameter named in the text, e.g. 'TOC Analysator POU kalibriert'
    select c.event_id, k.parameter
    from cal_events c
    join {{ ref('analyzer_keywords') }} k
        on regexp_matches(c.activity, '(?i)(^|[^A-Za-z])' || k.keyword || '([^A-Za-z]|$)')
),

event_periods as (
    select
        t.tag,
        c.ts_utc - interval 30 minute                         as start_utc,
        c.ts_utc + to_seconds(cast(c.mask_hours * 3600 as bigint)) as end_utc,
        'diary: ' || c.activity                               as reason
    from cal_events c
    join {{ ref('tags') }} t on t.unit_id = c.unit_id and t.is_analyzer
    where t.parameter in (select parameter from named n where n.event_id = c.event_id)
       or not exists (select 1 from named n where n.event_id = c.event_id)
)

select tag, start_utc, end_utc, reason from status_periods
union all
select tag, start_utc, end_utc, reason from event_periods
