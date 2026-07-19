# 0003 — Materialise fct_sales incrementally, keep the other facts as full tables

Status: accepted
Date: 2026-07-19

## Context

Sales is the largest fact and grows by date — new days append, old days rarely change.
Rebuilding the whole table on every run rescans all of history to add one day's worth of
rows, which is exactly the pattern incremental models exist to avoid.

## Decision

Materialise `fct_sales` as `incremental`, processing only rows from the latest loaded
day onward (`sale_date >= max(sale_date)`), with `delete+insert` on `sale_id`. The
delete+insert keeps the run idempotent: if a day arrives in more than one batch,
re-running it replaces that day's rows rather than duplicating them.

`fct_inventory` and `fct_purchase_orders` stay full-refresh tables for now. At the
current volume the rebuild is sub-second, and inventory in particular is a daily
snapshot where past rows are stable but the modelling is simpler kept whole.

## Consequences

Daily runs get cheap as history grows. The cost is the usual incremental caveats: a
change to the model's logic needs a `--full-refresh` to rewrite old rows, and the
`>= max` boundary assumes days load in order. Both are acceptable here and called out so
the behaviour isn't surprising. Revisit the other facts if they grow enough to feel the
full rebuild.
