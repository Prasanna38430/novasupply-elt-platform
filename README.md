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

Further steps are added here as the pipeline grows.

## Cost

Local DuckDB development is free. Cloud cost notes — S3 storage and Snowflake credit
consumption — will live in `docs/cost.md` once we reach the cloud phase.

## Limitations and trade-offs

Tracked honestly as the project matures: the data is synthetic, the Snowflake trial is
time-boxed, and a few choices favour learning value over production scale. Details land
in this section as those trade-offs are made.
