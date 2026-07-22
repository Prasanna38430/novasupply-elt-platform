# 0005 — Run Airflow with LocalExecutor, and keep dbt in its own virtualenv

Status: accepted
Date: 2026-07-22

## Context

The Airflow compose file most people start from runs Postgres, Redis, a webserver, a
scheduler, a triggerer and one or more Celery workers, and it expects 4-6 GB of RAM. The
development machine here gives Docker 2 GB and 2 CPUs (capped in `.wslconfig`). That
stack would spend its time being OOM-killed.

Separately, Airflow and dbt are awkward roommates. Both pin Jinja2, click and a handful
of other libraries, and the versions they want do not agree. Installing dbt directly into
the Airflow image means fighting the resolver on every upgrade.

## Decision

Run LocalExecutor with Postgres as the only supporting service: no Redis, no Celery
worker, no Flower. The webserver is held to one gunicorn worker and the scheduler to one
parsing process, and example DAGs are switched off.

Install dbt into a separate virtualenv inside the image (`/home/airflow/dbt-venv`) and
have the DAG call that interpreter by absolute path.

## Consequences

The stack fits comfortably: measured at roughly 960 MB across all three containers, about
half the available memory, with a full pipeline run taking around five minutes. The
actual limit turned out to be CPU, not memory — the scheduler sits near 83% during dbt
tasks — so throwing more RAM at it would not help.

LocalExecutor runs tasks as subprocesses on the scheduler host, so it does not scale
across machines. That is the right trade for a single-node project and a well-understood
production pattern for small deployments; moving to Celery or Kubernetes executors later
is a compose change, not a rewrite of the DAG.

Keeping dbt in its own virtualenv means the two tools upgrade independently. The cost is
that the DAG refers to interpreters by absolute path, which looks unusual until you know
why.
