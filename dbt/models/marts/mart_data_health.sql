-- Per source folder: files, duplicates, failures, values, time covered.
select
    l.source,
    count(*) filter (where l.status = 'loaded')            as files_loaded,
    count(*) filter (where l.status = 'duplicate_skipped') as files_duplicate,
    count(*) filter (where l.status = 'failed')            as files_failed,
    sum(l.values_loaded) filter (where l.status = 'loaded') as values_loaded,
    max(l.loaded_at)                                       as last_loaded_at,
    arg_max(l.message, l.loaded_at) filter (where l.status = 'failed') as last_failure
from {{ source('landing', 'load_log') }} l
group by 1
