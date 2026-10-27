-- Units in the export header that differ from the tag catalogue.
select distinct r.tag, r.unit_raw as unit_in_export, t.unit as unit_in_catalogue, r.source_file
from {{ ref('stg_readings') }} r
join {{ ref('tags') }} t using (tag)
where r.unit_raw is not null and r.unit_raw <> t.unit
