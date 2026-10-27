-- Process values only (analyser status columns are split off into stg_analyzer_status).
select source, tag, ts_local, ts_utc, dst_repeat, raw_value, value_num, parse_status, unit_raw,
       resolution_s, source_file, file_row, batch_id
from {{ source('landing', 'readings') }}
where tag not like '%.STATUS'
