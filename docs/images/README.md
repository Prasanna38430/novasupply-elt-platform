# README screenshots

Drop the images named below into this folder. Each one has a matching placeholder comment
in the top-level README. To make an image show, open README.md, find its `SCREENSHOT`
comment, and replace the whole comment with the `![...](...)` line printed inside it. Until
you do that, nothing renders, so the README never shows a broken image.

All of these are safe to commit. Before committing, blur or crop anything sensitive: the
AWS console shows your 12-digit account id top-right, and Snowsight shows your account
identifier. Neither is a password, but tidy them out of habit.

## The five that matter most

1. `dashboard.png` (hero, top of README)
   - Run: `streamlit run dashboards/app.py`
   - Open http://localhost:8501
   - Frame the operations overview: the KPI row (out of stock, at risk, in transit,
     revenue) and the "SKUs at risk of stocking out" table.

2. `dbt-lineage.png` (Architecture section)
   - Run: `cd dbt` then `dbt docs generate --profiles-dir .`
   - Then: `dbt docs serve --profiles-dir . --port 8081`
   - Open http://localhost:8081, click the lineage graph icon (bottom right), frame the
     source -> staging -> intermediate -> marts graph.

3. `airflow-dag.png` (Orchestration section)
   - Run: `docker compose up -d`
   - Open http://localhost:8080 (admin / admin)
   - Open `novasupply_pipeline`, use the Grid or Graph view, frame all six tasks green.

4. `ci.png` (Continuous integration section)
   - Repo -> Actions tab -> open a green run -> frame both jobs succeeded.

5. `cost-report.png` (Cost section)
   - Run: `python scripts/snowflake_cost_report.py`
   - Screenshot the terminal output (the credits and the ~EUR 0.21 line).

## Optional extras, if you want more depth

- `snowflake-db.png` — Snowsight showing the NOVASUPPLY database and its schemas, or the
  three roles, or a query result. Proves it genuinely runs on Snowflake.
- `masking.png` — the same secure view returning real names to NOVASUPPLY_TRANSFORMER and
  `*** RESTRICTED ***` to NOVASUPPLY_ANALYST.
- `s3-raw-zone.png` — the AWS S3 console showing the `dt=` partitioned folders.

Add a matching `![...](docs/images/...)` line wherever you want these to appear.
