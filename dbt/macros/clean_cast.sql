{#
  Cast a raw text column to a real type, treating blanks and whitespace-only values as
  NULL first. RAW lands everything as text from CSV, so this is the one cleaning step
  every typed staging column wants: trim, turn empty strings into NULL, then cast.
#}
{% macro clean_cast(column_name, data_type) -%}
    cast(nullif(trim({{ column_name }}), '') as {{ data_type }})
{%- endmacro %}
