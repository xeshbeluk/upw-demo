select entry_date, time_raw, ts_local, ts_utc, unit_text, activity, technician, remark, parse_status,
       source_file, file_row
from {{ source('landing', 'diary') }}
