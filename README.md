# NovaSupply

[![CI](https://github.com/Prasanna38430/novasupply-elt-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/Prasanna38430/novasupply-elt-platform/actions/workflows/ci.yml)

A governed, cost-monitored ELT platform for retail and supply-chain analytics.

## The problem

A mid-size French retailer keeps sales, inventory, supplier and logistics data in
separate systems. Nobody can cleanly answer a question the operations team raises
every week: which SKUs are about to stock out, and which supplier delays caused it?
NovaSupply is the platform that answers it. It pulls the siloed data together, models
it into a star schema, tests it for trustworthiness, and serves the answer.

## Project status

Working end to end today: data generation, the DuckDB raw layer, the full dbt star
schema with SCD2 snapshots and an incremental fact, 119 data tests plus quarantining of
bad rows, Elementary observability, Airflow orchestration in Docker, and CI on every
push.

Not built yet: the Terraform/S3 infrastructure, the Snowflake migration with RBAC and PII
masking, the warehouse cost dashboard, and the Streamlit serving layer. The architecture
below describes the finished design; those pieces are named in the stack because they are
the plan, not because they exist.

## Architecture

<!-- Diagram added in the hardening phase. -->

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

```bash
git clone https://github.com/Prasanna38430/novasupply-elt-platform.git
cd novasupply-elt-platform
python -m venv .venv
```

On Windows:

```bash
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

On macOS or Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Nothing in `.env` needs filling in for local development — the defaults point at DuckDB.
The cloud values matter only from the Snowflake phase onward.

Then generate the synthetic data and load it into the local DuckDB warehouse:

```bash
python ingestion/generate_dimensions.py
python ingestion/generate_facts.py
python ingestion/load_raw.py
```

This writes date-partitioned CSVs under `data/raw/` and builds the `raw` schema in
`data/novasupply.duckdb`. Both are gitignored and reproduce identically from the seeded
generators.

Then transform with dbt. dbt is run from the `dbt/` directory:

```bash
cd dbt
dbt deps --profiles-dir .     # first time only: installs dbt_utils and Elementary
dbt build --profiles-dir .    # models, tests and the snapshot, in dependency order
```

Elementary's own models dominate the build time, so while iterating use
`dbt build --exclude elementary --profiles-dir .` and keep the full build for scheduled
runs and CI.

This builds the star schema (`dim_*`, `fct_*`) in the `marts` schema. To see Type-2
history appear, run the snapshot, apply the sample supplier change, and snapshot again:

```bash
dbt snapshot --profiles-dir .
python ../ingestion/simulate_supplier_change.py
dbt snapshot --profiles-dir .
```

`SUP-0002` then has two versions: the old row closed off with a `dbt_valid_to`, and the
new one current. The ingestion scripts resolve their paths against the repo root, so they
work from any directory.

## Orchestration

Airflow runs the whole pipeline on a nightly schedule. Bring it up with:

```bash
docker compose up -d --build
```

The UI is at http://localhost:8080 (admin / admin — local development only). The
`novasupply_pipeline` DAG chains the six steps in order:

```text
generate_dimensions -> generate_facts -> load_raw -> dbt_run -> dbt_snapshot -> dbt_test
```

A full run takes about five minutes. Tear it down with `docker compose down`, or
`docker compose down -v` to drop the Airflow metadata database as well.

The setup is deliberately lean — LocalExecutor with Postgres, no Celery or Redis — because
the container budget here is 2 GB. dbt lives in its own virtualenv inside the image so its
dependencies do not collide with Airflow's. Both choices are explained in
[ADR 0005](docs/adr/0005-airflow-localexecutor.md).

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

## Continuous integration

Every push and pull request to `main` rebuilds the platform from nothing on a clean
runner: generate the data, load it, `dbt build`, and run all 119 tests. It takes about 70
seconds. Because the generators are seeded, CI produces the same dataset every time, so a
failing test means the code changed rather than the data getting unlucky. A second job
parses the Airflow DAG, which otherwise only breaks when the scheduler tries to run it.

Build artefacts (`dbt/target`, `dbt/logs`) are uploaded on every run, pass or fail, so a
red build can be diagnosed without reproducing it locally.

## Cost

Local DuckDB development is free. Cloud cost notes — S3 storage and Snowflake credit
consumption — will live in `docs/cost.md` once we reach the cloud phase.

## Limitations and trade-offs

Tracked honestly as the project matures: the data is synthetic, the Snowflake trial is
time-boxed, and a few choices favour learning value over production scale. Details land
in this section as those trade-offs are made.
