-- Analyser status columns (0 ok, 1 calibration, 2 maintenance, 3 fault) as their own stream.
select
    regexp_replace(tag, '\.STATUS$', '') as tag,
    ts_utc,
    cast(value_num as integer)           as status_code,
    source_file
from {{ source('landing', 'readings') }}
where tag like '%.STATUS' and parse_status = 'ok'
