# 0001 — Build on DuckDB locally, switch to Snowflake for the cloud phase

Status: accepted
Date: 2026-07-18

## Context

The platform targets Snowflake, but Snowflake has no permanent free tier — only a
30-day trial with a credit cap. This project is built over several weeks, and most of
that time goes into writing and re-running dbt models. That iterative work would burn a
trial quickly, and requiring cloud credentials from day one adds setup friction to
every early step, which slows down learning.

## Decision

Develop and test the whole dbt project against DuckDB, a free in-process engine whose
SQL is close enough to Snowflake's for our models. Keep the warehouse choice behind a
dbt profile so the same models run on either engine. Only once the pipeline works end
to end do we create the Snowflake trial and flip the profile — at that point to capture
real-engine behaviour, RBAC, PII masking, and the credit-cost dashboard.

## Consequences

The good: no cost and no account setup during the long build phase, faster local runs,
and the trial clock only starts when we actually need it.

The cost: a few dialect differences surface at switch time. DuckDB and Snowflake differ
on some functions, and on features like clustering keys that DuckDB doesn't have. We
accept this and document the migration explicitly — that write-up is itself worth
showing.

Alternatives considered. Developing directly on the Snowflake trial: rejected, it
wastes the clock and blocks progress behind account setup. Using BigQuery's always-free
tier instead: rejected, it moves the project away from the Snowflake target it is meant
to demonstrate.
