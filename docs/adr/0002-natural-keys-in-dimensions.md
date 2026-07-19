# 0002 — Use natural business keys in dimensions, not surrogate keys

Status: accepted
Date: 2026-07-19

## Context

Kimball dimensional modelling usually gives each dimension a surrogate key — a
meaningless integer — rather than reusing the source system's business key. Surrogate
keys earn their place when business keys are unstable, non-unique, or collide across
several source systems, and they are needed for Type 2 history, where one business
entity has several rows over time.

## Decision

Keep the natural keys (`supplier_id`, `product_id`, `store_id`) as the dimension keys
in the marts. They are already clean, stable, unique and come from a single source. The
fact tables reference them directly.

## Consequences

Joins stay simple and the models read plainly, at the cost of not showing the
surrogate-key pattern on every dimension. Where history genuinely matters — suppliers
whose lead time or reliability changes over time — we capture it with a dbt snapshot
(SCD2), and dbt keys that with its own surrogate id. So the pattern still appears in the
project, in the one place it pays off, instead of as ceremony everywhere.

Worth revisiting if a second source system is ever added, since business keys could
then collide and a surrogate layer would decouple the marts from that mess.
