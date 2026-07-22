"""Nightly NovaSupply pipeline: generate raw data, load it, then transform and test.

The tasks run the same commands a developer runs by hand, in the same order, so there is
a single definition of how the pipeline executes rather than one for humans and another
for the scheduler.

dbt lives in its own virtualenv inside the image (see airflow/Dockerfile), so both the
ingestion scripts and dbt are invoked by absolute path rather than whatever happens to be
first on PATH.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

PROJECT_DIR = "/opt/airflow/project"
PYTHON = "/home/airflow/dbt-venv/bin/python"
DBT = "/home/airflow/dbt-venv/bin/dbt"

default_args = {
    "owner": "data-engineering",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="novasupply_pipeline",
    description="Generate raw retail data, load to DuckDB, transform and test with dbt",
    default_args=default_args,
    start_date=datetime(2026, 7, 1),
    schedule="0 4 * * *",
    catchup=False,
    # DuckDB allows a single writer, so overlapping runs would collide.
    max_active_runs=1,
    tags=["novasupply", "elt"],
) as dag:

    generate_dimensions = BashOperator(
        task_id="generate_dimensions",
        bash_command=f"cd {PROJECT_DIR} && {PYTHON} ingestion/generate_dimensions.py",
    )

    generate_facts = BashOperator(
        task_id="generate_facts",
        bash_command=f"cd {PROJECT_DIR} && {PYTHON} ingestion/generate_facts.py",
    )

    load_raw = BashOperator(
        task_id="load_raw",
        bash_command=f"cd {PROJECT_DIR} && {PYTHON} ingestion/load_raw.py",
    )

    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=f"cd {PROJECT_DIR}/dbt && {DBT} run --profiles-dir .",
    )

    # Snapshots read the staging views, so they run after the models are built.
    dbt_snapshot = BashOperator(
        task_id="dbt_snapshot",
        bash_command=f"cd {PROJECT_DIR}/dbt && {DBT} snapshot --profiles-dir .",
    )

    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=f"cd {PROJECT_DIR}/dbt && {DBT} test --profiles-dir .",
    )

    (
        generate_dimensions
        >> generate_facts
        >> load_raw
        >> dbt_run
        >> dbt_snapshot
        >> dbt_test
    )
