# NovaSupply

[![CI](https://github.com/Prasanna38430/novasupply-elt-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/Prasanna38430/novasupply-elt-platform/actions/workflows/ci.yml)

A governed, cost-monitored ELT platform for retail and supply-chain analytics.

## The problem

A mid-size French retailer keeps sales, inventory, supplier and logistics data in
separate systems. Nobody can cleanly answer a question the operations team raises
every week: which SKUs are about to stock out, and which supplier delays caused it?
NovaSupply is the platform that answers it. It pulls the siloed data together, models
it into a star schema, tests it for trustworthiness, and serves the answer.

## Architecture

Python generators land raw data in a date-partitioned raw zone, locally and in S3. The
warehouse — DuckDB for development, Snowflake in the cloud — holds it across RAW, STAGING,
INTERMEDIATE and MARTS layers, with QUARANTINE and SNAPSHOTS alongside. dbt does the
transformation into a star schema; Airflow runs the sequence on a schedule; Terraform
provisions S3 and the Snowflake objects; GitHub Actions rebuilds everything on every push;
Elementary records what each run did; a Streamlit app serves the answer.

The diagram and the reasoning behind each layer are in
[docs/architecture.md](docs/architecture.md).

**The same dbt models build on both warehouses**, and produce identical results — row
counts, revenue, late and open orders, stockout counts and the date dimension all match
exactly across DuckDB and Snowflake. Switching is a profile change, not a fork.

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

## Documentation

Every model and column is documented in the dbt project itself, alongside the tests that
assert it. To browse the lineage graph and column-level docs:

```bash
cd dbt
dbt docs generate --profiles-dir .
dbt docs serve --profiles-dir .
```

Written docs live in `docs/`: [architecture](docs/architecture.md),
[data dictionary](docs/data_dictionary.md), [cost](docs/cost.md), and six
[architecture decision records](docs/adr/) covering the choices that were genuinely
arguable.

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

The entire Snowflake migration — loading 250k rows from S3 and building every model and
test — consumed **0.078 credits, about EUR 0.21**. S3 holds 11.4 MiB against a 5 GB free
allowance.

That is not an accident of small data. The warehouse is XSMALL, starts suspended, and
auto-suspends after 60 seconds, which is the single most effective cost control in
Snowflake and the most commonly missed: the default of 600 seconds bills ten minutes of
idling after every query. Measured figures and what would actually change them are in
[docs/cost.md](docs/cost.md).

## Serving

```bash
streamlit run dashboards/app.py
```

Shows SKUs at risk of stocking out with their supplier, supplier lateness rankings, the
stockout rate by supplier reliability tier, a revenue trend, and a data-quality panel. A
sidebar toggle switches the whole dashboard between DuckDB and Snowflake.

## Limitations and trade-offs

Worth being straight about what this is and is not.

**The data is synthetic.** It is generated by a seeded inventory simulation, not extracted
from a real retailer. That is deliberate — it makes the project reproducible and puts a
genuine causal chain in the data — but no amount of realistic shaping makes it real data.

**There is no personal data, so RGPD is demonstrated rather than exercised.** Suppliers are
companies. The role-based masking protects commercially sensitive supplier terms, which is
the same mechanism a real customer table would use, applied to the most sensitive thing
actually present. See [ADR 0006](docs/adr/0006-secure-view-instead-of-masking-policy.md).

**Column masking uses a secure view, not a masking policy.** Dynamic Data Masking is
Enterprise Edition and this trial is Standard. A masking policy attaches to the column and
protects it everywhere; a secure view only protects whoever is pointed at the view. The
gap is real and is documented rather than papered over.

**Airflow runs LocalExecutor on a single node.** The container budget on the development
machine is 2 GB, which the standard Celery stack would not fit in. LocalExecutor is a
legitimate small-deployment pattern, but it does not scale across machines
([ADR 0005](docs/adr/0005-airflow-localexecutor.md)).

**The Terraform IAM user has broader rights than ideal.** `AmazonS3FullAccess` and
`IAMFullAccess`, because true least-privilege is awkward when Terraform is creating the
IAM resources itself. In a real account this would be tightened to a hand-written policy.

**Terraform state is local.** Fine for one person; a team would need a remote backend with
locking before anyone else could safely apply.

**Only `fct_sales` is incremental.** The other facts rebuild fully because at this volume
it takes under a second. That would need revisiting long before real production volume
([ADR 0003](docs/adr/0003-incremental-sales-fact.md)).

**The Snowflake trial is time-boxed.** When it lapses, everything still runs on DuckDB —
which is exactly why the project was built that way round.
