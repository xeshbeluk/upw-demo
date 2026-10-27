-- Classified maintenance / plant events with the analysis windows of their type.
select
    e.event_id,
    e.ts_utc,
    e.ts_local,
    e.event_type,
    et.label                 as event_label,
    e.unit_id,
    u.unit_name,
    e.activity,
    e.technician,
    e.remark,
    et.is_maintenance,
    et.window_before_h,
    et.window_after_h,
    et.default_tags
from {{ ref('int_events') }} e
join {{ ref('event_types') }} et on et.event_type = e.event_type
left join {{ ref('process_units') }} u on u.unit_id = e.unit_id
where e.resolution_status = 'ok'
