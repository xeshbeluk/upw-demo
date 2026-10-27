{{ config(severity='warn') }}
select * from {{ ref('qa_unclassified_events') }}
