-- A unit change in the export must be caught before values are compared with limits.
select * from {{ ref('qa_unit_mismatch') }}
