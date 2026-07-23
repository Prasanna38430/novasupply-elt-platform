# Cost

What this platform actually costs to run, with measured numbers rather than estimates.
Regenerate the Snowflake figures with `python scripts/snowflake_cost_report.py`.

## Local development: free

Everything up to the cloud phase runs on DuckDB and the local filesystem. No accounts, no
bills, no trial clock. That was the point of [ADR 0001](adr/0001-local-first-duckdb.md):
the long, iterative part of the work — writing and re-running dbt models — is exactly the
part that would burn a trial, and it does not need a cloud warehouse to be correct.

## Snowflake

Measured on 2026-07-23, after loading the full dataset from S3 and building every model
and test on Snowflake:

| Item | Measured |
|---|---|
| Credits used by `NOVASUPPLY_WH` | **0.0781** |
| Approximate cost at Standard on-demand (EUR 2.75/credit) | **~EUR 0.21** |
| Table storage | 0.007 GB |
| Stage storage | 0.001 GB |
| Full `dbt build` wall time | 33 seconds |

For scale: the trial provides roughly 400 credits. The entire cloud phase of this project
consumed under 0.02% of it.

### Why it is that cheap

**The warehouse is XSMALL.** One credit per hour while running. Nothing about 250k rows
justifies more, and sizing up would not have made the build meaningfully faster — it would
just bill more per second.

**It auto-suspends after 60 seconds.** This is the single most effective cost control in
Snowflake and the most commonly missed. A warehouse left running idle bills by the second
for doing nothing; the default of 600 seconds means ten minutes of paid idling after every
query. Sixty seconds is short enough to stop paying almost immediately and long enough to
avoid resume latency between the steps of a dbt run.

**It starts suspended.** Creating the warehouse cost nothing, and it only woke when work
arrived.

The busiest query types on the warehouse were `SELECT` (135 queries, 15.4s), `COPY` (6
queries, 6.5s) and `CREATE_TABLE_AS_SELECT` (9 queries, 4.9s) — the shape you would expect
from a load followed by a dbt build, with no long-running outliers.

## AWS

| Item | Measured | Free tier |
|---|---|---|
| S3 objects in the raw zone | 269 | — |
| S3 storage | 11.4 MiB | 5 GB |
| Region | eu-west-3 (Paris) | — |

Comfortably inside the free allowance, and the account is on the Free Plan, which cannot
incur charges without an explicit upgrade. A zero-spend budget alert is configured as a
second line of defence.

The bucket keeps versions of every object, which would otherwise accumulate storage cost
indefinitely, so a lifecycle rule expires non-current versions after 30 days and aborts
incomplete multipart uploads after 7.

**S3 and Snowflake are both in `eu-west-3`.** Cross-region reads would add data-transfer
charges and latency for no benefit; matching them costs nothing and avoids the problem
entirely.

## What would change the picture

The numbers above reflect roughly 250,000 rows and a handful of builds a day. Things that
would actually move the cost:

- **Frequency.** Cost scales with how often the warehouse wakes, not with how much data
  sits in it. An hourly schedule costs roughly 24 times a daily one.
- **Elementary.** Its 30 observability models dominate build time and therefore warehouse
  seconds. Worth it on scheduled runs and in CI; excluded while iterating
  (`dbt build --exclude elementary`), which is the trade recorded in
  [ADR 0004](adr/0004-elementary-for-observability.md).
- **Full refreshes.** `fct_sales` is incremental precisely so that daily runs touch one
  day rather than ninety ([ADR 0003](adr/0003-incremental-sales-fact.md)). Forcing
  `--full-refresh` on a schedule would throw that away.
- **Warehouse size.** Going up a size doubles the per-second rate. At this volume it would
  buy nothing.
