-- Maintenance diary -> classified events.
--   event type = longest keyword from event_keywords contained in the activity text
--   unit       = longest alias from unit_aliases contained in the 'Anlage' text
-- Entries that match no keyword are kept with resolution_status 'unclassified' (quarantine).
with d as (
    select row_number() over (order by ts_utc, file_row) as entry_no, *
    from {{ ref('stg_diary') }}
),

kw as (
    select d.entry_no, k.event_type, length(k.keyword) as len
    from d join {{ ref('event_keywords') }} k on contains(lower(d.activity), lower(k.keyword))
),

type_best as (
    select entry_no, arg_max(event_type, len) as event_type, count(distinct event_type) as n_types
    from kw group by 1
),

ua as (
    select d.entry_no, a.unit_id, length(a.alias) as len
    from d join {{ ref('unit_aliases') }} a on contains(lower(d.unit_text), lower(a.alias))
),

unit_best as (
    select entry_no, arg_max(unit_id, len) as unit_id from ua group by 1
)

select
    md5(concat_ws('|', cast(d.ts_utc as varchar), d.unit_text, d.activity)) as event_id,
    d.entry_no,
    d.ts_utc,
    d.ts_local,
    d.unit_text,
    d.activity,
    d.technician,
    d.remark,
    t.event_type,
    u.unit_id,
    case
        when d.parse_status <> 'ok' then d.parse_status
        when t.event_type is null   then 'unclassified'
        when t.n_types > 1          then 'ambiguous_type'
        when u.unit_id is null      then 'unknown_unit'
        else 'ok'
    end as resolution_status,
    d.source_file,
    d.file_row
from d
left join type_best t using (entry_no)
left join unit_best u using (entry_no)
