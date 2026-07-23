"""Load the S3 raw zone into Snowflake's RAW schema.

The Snowflake counterpart of load_raw.py. Same contract: every column lands as text, plus
two lineage columns, so RAW stays a faithful copy of the source files and dbt staging does
all the casting. The dbt models are therefore identical on DuckDB and Snowflake.

Terraform provisions the storage integration; this creates the stage that uses it, then
COPY INTO for each table.

    python ingestion/upload_to_s3.py
    python ingestion/load_snowflake_raw.py
"""
from __future__ import annotations

import os

import snowflake.connector

# (target table, prefix in the bucket, source columns in file order)
SOURCES = [
    ("SUPPLIERS", "suppliers/", [
        "supplier_id", "supplier_name", "country", "city",
        "nominal_lead_time_days", "reliability_score", "valid_from",
    ]),
    ("PRODUCTS", "products/", [
        "product_id", "product_name", "category", "supplier_id",
        "unit_cost_eur", "unit_price_eur",
    ]),
    ("STORES", "stores/", ["store_id", "store_name", "city", "region"]),
    ("SALES", "sales/", [
        "sale_id", "sale_date", "store_id", "product_id", "quantity",
        "unit_price_eur", "discount_pct", "amount_eur",
    ]),
    ("INVENTORY_SNAPSHOTS", "inventory/", [
        "snapshot_date", "store_id", "product_id",
        "on_hand_qty", "reorder_point", "in_transit_qty",
    ]),
    ("PURCHASE_ORDERS", "purchase_orders/", [
        "po_id", "order_date", "supplier_id", "product_id", "store_id",
        "ordered_qty", "promised_date", "actual_delivery_date", "received_qty",
    ]),
]

STAGE = "NOVASUPPLY_RAW_STAGE"
FILE_FORMAT = "NOVASUPPLY_CSV"


def connect():
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.environ.get("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        schema="RAW",
        login_timeout=60,
    )


def main() -> None:
    bucket = os.environ["S3_RAW_BUCKET"]
    database = os.environ["SNOWFLAKE_DATABASE"]

    con = connect()
    cur = con.cursor()
    cur.execute(f"use schema {database}.RAW")

    # SKIP_HEADER because the generators write a header row; EMPTY_FIELD_AS_NULL turns the
    # blank delivery dates on open purchase orders into real NULLs, matching DuckDB.
    cur.execute(f"""
        create or replace file format {FILE_FORMAT}
            type = csv
            field_delimiter = ','
            skip_header = 1
            field_optionally_enclosed_by = '"'
            empty_field_as_null = true
            null_if = ('')
    """)

    cur.execute(f"""
        create or replace stage {STAGE}
            storage_integration = NOVASUPPLY_S3_INTEGRATION
            url = 's3://{bucket}/'
            file_format = {FILE_FORMAT}
    """)
    print(f"stage {STAGE} -> s3://{bucket}/")

    for table, prefix, columns in SOURCES:
        column_ddl = ",\n            ".join(f"{c} varchar" for c in columns)
        cur.execute(f"""
            create or replace table {table} (
            {column_ddl},
            _source_file varchar,
            _loaded_at timestamp_ltz
            )
        """)

        # metadata$filename and the load timestamp give the same lineage columns the
        # DuckDB loader adds.
        select_list = ",\n                ".join(
            f"t.${i}" for i in range(1, len(columns) + 1)
        )
        cur.execute(f"""
            copy into {table}
            from (
                select
                {select_list},
                metadata$filename,
                current_timestamp()
                from @{STAGE}/{prefix} t
            )
            file_format = (format_name = {FILE_FORMAT})
            on_error = abort_statement
        """)

        n = cur.execute(f"select count(*) from {table}").fetchone()[0]
        print(f"loaded {database}.RAW.{table:<20} {n:>7} rows")

    con.close()


if __name__ == "__main__":
    main()
