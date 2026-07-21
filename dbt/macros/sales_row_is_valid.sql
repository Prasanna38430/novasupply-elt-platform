{#
  The validity rule for a sale row, defined once so stg_sales and quarantine_sales
  cannot drift apart: one keeps the rows where this is true, the other keeps the rest.

  Every clause pairs an is-not-null check with its comparison, so the expression
  evaluates to true or false and never to NULL. That matters, because `not (NULL)` is
  NULL, and a row that satisfied neither side would silently vanish from both models.
#}
{% macro sales_row_is_valid() -%}
    sale_date is not null
    and store_id is not null
    and product_id is not null
    and quantity is not null and quantity > 0
    and amount_eur is not null and amount_eur >= 0
    and discount_pct is not null and discount_pct between 0 and 1
{%- endmacro %}
