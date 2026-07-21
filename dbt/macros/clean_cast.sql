{#
  Cast a raw text column to a real type, treating blanks and whitespace-only values as
  NULL first. RAW lands everything as text from CSV, so this is the one cleaning step
  every typed staging column wants: trim, turn empty strings into NULL, then cast.

  try_cast rather than cast, deliberately: a single unparseable value should not abort
  the whole model. Bad values land as NULL and get picked up by the quarantine models
  and the not_null tests, which is where we want to deal with them.
#}
{% macro clean_cast(column_name, data_type) -%}
    try_cast(nullif(trim({{ column_name }}), '') as {{ data_type }})
{%- endmacro %}
