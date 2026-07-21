# 0004 — Adopt Elementary for data observability, on DuckDB from the start

Status: accepted
Date: 2026-07-19

## Context

dbt tests give a pass/fail at the moment they run and nothing else. They do not tell you
whether a test has been flapping for a week, which models are getting slower, or when a
column quietly changed type. That history is what turns "the tests passed" into an
actual data-quality story, and it is the part reviewers of this project will look for.

The assumption going in was that Elementary only supported the big cloud warehouses and
would have to wait until we moved to Snowflake. That turned out to be out of date:
recent Elementary releases added DuckDB support, and version 0.25.1 builds and collects
results against our local warehouse without any special handling. Verified rather than
assumed, after an older write-up claimed otherwise.

## Decision

Adopt Elementary now, during the local DuckDB phase, rather than bolting observability
on after the move to Snowflake. It writes its own tables into a dedicated `elementary`
schema and collects run results, test outcomes, timings and schema snapshots on every
invocation.

## Consequences

We get test-result history, model run times and schema-change tracking for free from
here on, and the same package carries over to Snowflake unchanged.

The cost is build time. Elementary contributes 30 models of its own, and they dominate a
full run — `dbt_tests` and `dbt_columns` alone take roughly 100 seconds together, which
is more than the entire NovaSupply pipeline. For fast iteration use
`dbt build --exclude elementary`; let the full build with Elementary run on a schedule
and in CI, where the extra minute does not matter. If that stops being an acceptable
trade, the fallback is to run Elementary only on the nightly job.
