{#
  Date parts that DuckDB and Snowflake spell differently.

  dbt ships cross-database macros for the common cases (datediff, current_timestamp),
  and those are used directly in the models. ISO week and ISO weekday are not among
  them, so they are dispatched per adapter here. adapter.dispatch picks
  snowflake__<name> when running against Snowflake and falls back to default__<name>
  everywhere else, which is what DuckDB uses.

  Keeping the difference in one place is the point: the models stay identical across
  both warehouses, and the migration is a profile switch rather than a fork.
#}

{% macro iso_day_of_week(date_column) -%}
    {{ return(adapter.dispatch('iso_day_of_week', 'novasupply')(date_column)) }}
{%- endmacro %}

{% macro default__iso_day_of_week(date_column) -%}
    extract(isodow from {{ date_column }})
{%- endmacro %}

{% macro snowflake__iso_day_of_week(date_column) -%}
    dayofweekiso({{ date_column }})
{%- endmacro %}


{% macro iso_week(date_column) -%}
    {{ return(adapter.dispatch('iso_week', 'novasupply')(date_column)) }}
{%- endmacro %}

{% macro default__iso_week(date_column) -%}
    extract(week from {{ date_column }})
{%- endmacro %}

{% macro snowflake__iso_week(date_column) -%}
    weekiso({{ date_column }})
{%- endmacro %}
