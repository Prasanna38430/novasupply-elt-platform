FROM apache/airflow:2.10.5-python3.11

# git lets `dbt deps` resolve packages that resolve to git refs.
USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*
USER airflow

# dbt and Airflow both pin Jinja2, click and friends, and they disagree. Installing dbt
# into its own virtualenv keeps the two dependency trees apart instead of fighting a
# resolver. The DAG calls the interpreters in this venv by absolute path.
COPY requirements.txt /tmp/novasupply-requirements.txt
RUN python -m venv /home/airflow/dbt-venv \
 && /home/airflow/dbt-venv/bin/pip install --no-cache-dir --upgrade pip \
 && /home/airflow/dbt-venv/bin/pip install --no-cache-dir -r /tmp/novasupply-requirements.txt
