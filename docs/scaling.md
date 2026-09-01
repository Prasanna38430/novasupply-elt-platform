# Scaling

Where this platform stops working, with the arithmetic rather than a shrug. Most
architectures fail on contact with volume, and the useful thing to know about one is not
whether it scales but *which part gives first, and at what number*.

Nothing here has been load-tested. These are the limits the design implies, measured
against the volumes it actually runs at today.

## What it runs at now

Measured on the current build:

| Table | Rows |
|---|---|
| `fct_inventory` | 144,000 |
| `fct_sales` | 100,946 |
| `fct_purchase_orders` | 8,390 |
| `fct_contract_compliance` | 7,241 |
| Warehouse file | 30 MB |
| Contract corpus | 25 documents, 180 chunks |

A full `dbt build` takes about 47 seconds, most of it Elementary's own models. CI rebuilds
the whole platform from nothing in about 90 seconds.

## The grain that breaks first

`fct_inventory` is a **daily snapshot** at store x SKU x day. That is a multiplicative
grain, and it is the number to watch:

| | stores | SKUs | rows/day | rows/year |
|---|---|---|---|---|
| here | 8 | 200 | 1,600 | 584 thousand |
| a mid-size French retailer | 150 | 30,000 | 4.5 million | **1.6 billion** |

The same shape of platform, pointed at a real chain, produces roughly three thousand times
the daily volume. Snapshot facts are the standard way to answer "what was in stock on this
date", and they are also the standard way to accumulate a billion rows nobody planned for.

[ADR 0003](adr/0003-incremental-sales-fact.md) already decided that `fct_inventory` and
`fct_purchase_orders` stay full-refresh "for now", on the grounds that the rebuild is
sub-second at current volume. That reasoning is right and this document does not overturn
it. What it adds is the number where "for now" expires: somewhere in the low millions of
rows, a full nightly rebuild of a snapshot fact stops being sub-second and starts being the
whole run.

## What gives, in order

1. **`load_raw.py`, before any dbt model.** It does `create or replace table` over a glob
   of every partition, so each run re-reads and re-copies the entire history into RAW. At a
   hundred days of small CSVs that is fine; at three years of real partitions it is
   re-ingesting terabytes to add a day. This is the first thing to fall over, and it is not
   a dbt problem.
2. **The three full-refresh facts.** `fct_inventory`, `fct_purchase_orders` and
   `fct_contract_compliance` all rebuild whole. Sales is already incremental.
3. **Contract extraction, which is the worst of them.** Twenty-five documents took about
   twenty minutes on CPU, roughly **48 seconds per document**, single-threaded with no
   queue and no batching. Five thousand supplier agreements would take **67 hours**. This
   does not degrade gracefully, it simply stops being runnable, and no amount of dbt
   tuning touches it.
4. **The extraction seed.** A committed CSV is the right medium for twenty-five rows that a
   human should read in a diff ([ADR 0009](adr/0009-llm-steps-outside-ci.md)). At fifty
   thousand rows, git is not a database.
5. **DuckDB's single writer.** Already documented in
   [ADR 0001](adr/0001-local-first-duckdb.md), and the reason the DAG runs
   `max_active_runs=1`. Snowflake is the stated path out.
6. **Airflow on LocalExecutor**, single node, by the container budget in
   [ADR 0005](adr/0005-airflow-localexecutor.md).
7. **Brute-force vector search, last and later than people expect.** 180 chunks scanned per
   query today. This holds into the tens of thousands before an HNSW index earns its
   keep, which is what [ADR 0008](adr/0008-retrieval-over-the-contract-corpus.md) claims and
   is the least urgent item on this list.

## What each fix would be

- **Partition-scoped loading.** Land only new `dt=` partitions rather than globbing all of
  them, tracked by a high-water mark. Removes the first failure entirely.
- **Incremental snapshots, then retention.** Making `fct_inventory` incremental fixes the
  write cost but not the volume: a billion rows is a billion rows however they arrived. The
  real answer is partitioning or clustering on `snapshot_date`, plus a retention policy or
  a rolled-up monthly grain for anything older than the operational window.
- **Batched, parallel extraction off a queue**, with a GPU or a hosted model. 48 seconds a
  document is a CPU-bound single-thread figure and is not inherent to the task.
- **A table instead of a seed** once extracted terms outgrow review-in-a-diff, with the
  reviewability moving to a test rather than to git history.
- **Snowflake and a real executor** for the two already-documented ceilings.

## What survives

Worth being clear that the failures above are volume failures, not shape failures. The
parts that would carry over to a system a thousand times larger are the ones that were
designed rather than defaulted:

- the **layering** (RAW, STAGING, INTERMEDIATE, MARTS) is what you would keep while
  swapping every materialisation underneath it;
- **quarantine instead of failure**, so one malformed row degrades a number rather than
  stopping a nightly run;
- **tests as contracts**, including the two singular tests that guard the term-period join
  and the penalty cap;
- **cross-engine portability through macros** rather than a fork per warehouse;
- **caching expensive model output as a reviewed artefact**, which is the right pattern
  even though CSV is the wrong medium past a certain size.

The honest summary is that this is a correctly shaped platform running at demo volume. The
shape would survive scaling. Several of the materialisations and all of the LLM throughput
would not, and those are the parts that would be rewritten first.
