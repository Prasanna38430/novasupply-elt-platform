# NovaSupply

A governed, cost-monitored ELT platform for retail and supply-chain analytics.

## The problem

A mid-size French retailer keeps sales, inventory, supplier and logistics data in
separate systems. Nobody can cleanly answer a question the operations team raises
every week: which SKUs are about to stock out, and which supplier delays caused it?
NovaSupply is the platform that answers it. It pulls the siloed data together, models
it into a star schema, tests it for trustworthiness, and serves the answer.

## Architecture

<!-- Diagram added in Phase 9. -->

Python extractors land raw data in a partitioned raw zone (local files, then S3). The
warehouse (DuckDB locally, Snowflake in the cloud) holds it across RAW, STAGING and
MARTS layers. dbt does the transformation into a star schema; Airflow runs the whole
sequence on a schedule; Terraform provisions the cloud infrastructure; GitHub Actions
runs CI on every push; Elementary watches data quality; a Streamlit app serves the
result.

## Stack

- Ingestion: Python (pandas, Faker)
- Raw storage: partitioned local files, then AWS S3
- Warehouse: DuckDB for local dev, Snowflake for the cloud phase
- Transformation: dbt-core with the DuckDB and Snowflake adapters
- Orchestration: Apache Airflow (in Docker)
- Infrastructure as code: Terraform
- CI: GitHub Actions
- Data quality: dbt tests + Elementary
- Serving: Streamlit

## Why DuckDB first

The pipeline is built and tested locally on DuckDB, which is free and needs no cloud
accounts. Once it runs end to end, the dbt profile switches to a Snowflake 30-day
trial to capture real-engine behaviour, RBAC, PII masking and the warehouse cost
dashboard. The reasoning is in [docs/adr/0001-local-first-duckdb.md](docs/adr/0001-local-first-duckdb.md).

## Running it locally

Requires Python 3.11+ and git.

```
git clone <repo-url>
cd novasupply
python -m venv .venv
.venv\Scripts\activate        # Windows; use source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
copy .env.example .env         # then fill in values as needed
```

Then generate the synthetic data and load it into the local DuckDB warehouse:

```
python ingestion/generate_dimensions.py
python ingestion/generate_facts.py
python ingestion/load_raw.py
```

This writes date-partitioned CSVs under `data/raw/` and builds the `raw` schema in
`data/novasupply.duckdb`. Both are gitignored and reproduce identically from the seeded
generators.

Then transform with dbt. dbt is run from the `dbt/` directory:

```
cd dbt
dbt deps --profiles-dir .     # first time only: installs dbt_utils and Elementary
dbt build --profiles-dir .    # models, tests and the snapshot, in dependency order
```

Elementary's own models dominate the build time, so while iterating use
`dbt build --exclude elementary --profiles-dir .` and keep the full build for scheduled
runs and CI.

This builds the star schema (`dim_*`, `fct_*`) in the `marts` schema. To see Type-2
history appear, run the snapshot, apply the sample supplier change, and snapshot again:

```
dbt snapshot --profiles-dir .
python ../ingestion/simulate_supplier_change.py
dbt snapshot --profiles-dir .
```

Further steps are added here as the pipeline grows.

## Data quality

Three layers, because they catch different things.

**Tests** (119 of them) assert the contracts: dimension keys are unique, every fact
foreign key resolves, quantities are positive, `reliability_score` sits between 0 and 1,
and the fact grains hold. Alongside the generic tests there are singular tests for
business rules that structural checks miss — revenue reconciling to its own components,
`is_late` agreeing with the delivery dates it derives from.

**Quarantine** handles bad rows without stopping the line. Invalid sale rows are diverted
into `quarantine.quarantine_sales` with the reason they failed, while valid rows carry
on. A malformed row degrades the numbers slightly instead of failing the nightly run, and
someone can still go and look at what broke. `ingestion/simulate_bad_data.py` inserts
deliberately broken rows to demonstrate it.

**Elementary** keeps the history: test outcomes over time, model run durations, schema
changes. See [ADR 0004](docs/adr/0004-elementary-for-observability.md).

## Cost

Local DuckDB development is free. Cloud cost notes — S3 storage and Snowflake credit
consumption — will live in `docs/cost.md` once we reach the cloud phase.

## Limitations and trade-offs

Tracked honestly as the project matures: the data is synthetic, the Snowflake trial is
time-boxed, and a few choices favour learning value over production scale. Details land
in this section as those trade-offs are made.
