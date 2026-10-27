{{ config(severity='warn') }}
select * from {{ ref('qa_unknown_tags') }}
