"""Load the raw CSV files into the DuckDB warehouse as a RAW layer.

Every source lands in the `raw` schema, one table per entity, with all columns kept as
text — RAW is a faithful, untyped copy of what arrived. Type casting and cleaning happen
downstream in dbt staging. Two lineage columns are added: which file a row came from and
when it was loaded.

This is the local stand-in for a Snowflake COPY INTO. Run the generators first, then:

    python ingestion/load_raw.py
"""
from __future__ import annotations

import duckdb

from config import DUCKDB_PATH, RAW_DATA_DIR

# (raw table name, path relative to RAW_DATA_DIR). Globs pull in every dt= partition.
SOURCES = [
    ("suppliers", "suppliers/suppliers.csv"),
    ("products", "products/products.csv"),
    ("stores", "stores/stores.csv"),
    ("sales", "sales/dt=*/sales.csv"),
    ("inventory_snapshots", "inventory/dt=*/inventory.csv"),
    ("purchase_orders", "purchase_orders/dt=*/purchase_orders.csv"),
]


def main() -> None:
    con = duckdb.connect(str(DUCKDB_PATH))
    con.execute("create schema if not exists raw")

    for table, rel in SOURCES:
        glob = (RAW_DATA_DIR / rel).as_posix()
        con.execute(
            f"""
            create or replace table raw.{table} as
            select * exclude (filename),
                   filename as _source_file,
                   now()    as _loaded_at
            from read_csv('{glob}', union_by_name=true, all_varchar=true,
                          filename=true, hive_partitioning=false)
            """
        )
        n = con.execute(f"select count(*) from raw.{table}").fetchone()[0]
        print(f"loaded raw.{table:<20} {n:>7} rows")

    con.close()
    print(f"\nwarehouse: {DUCKDB_PATH}")


if __name__ == "__main__":
    main()
