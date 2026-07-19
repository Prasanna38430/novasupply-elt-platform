{#
  Use the schema configured on each model as-is (staging, intermediate, marts)
  instead of dbt's default, which prefixes it with the target schema and would give
  us main_staging, main_marts, and so on. Models with no schema set fall back to the
  target's default schema.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
