-- Diary entries the pipeline could not classify (no known keyword / unit). Fix: add the keyword
-- or alias in the reference tables, then rebuild.
select resolution_status, ts_local, unit_text, activity, technician, source_file, file_row
from {{ ref('int_events') }}
where resolution_status <> 'ok'
order by ts_local
