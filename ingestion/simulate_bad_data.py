"""Insert deliberately malformed sale rows so the quarantine models can be demonstrated.

Generated data is clean, which makes for a poor test of a safety net. Each row below
breaks a different validation rule, and they go straight into the raw landing table
where real bad data would turn up. Re-running ingestion/load_raw.py clears them out.

    python ingestion/simulate_bad_data.py
    (cd dbt && dbt build --profiles-dir .)   # run stays green; rows land in quarantine
"""
from __future__ import annotations

import duckdb

from config import DUCKDB_PATH

# sale_id, sale_date, store_id, product_id, quantity, unit_price, discount_pct, amount
BAD_ROWS = [
    ("SAL-BAD-001", "2026-07-18", "STO-001", "SKU-00001", "0",  "10.00", "0.0", "0.00"),
    ("SAL-BAD-002", "2026-07-18", "STO-001", "SKU-00002", "-3", "10.00", "0.0", "30.00"),
    ("SAL-BAD-003", "2026-07-18", "STO-002", "SKU-00003", "2",  "10.00", "0.0", "abc"),
    ("SAL-BAD-004", "2026-07-18", "STO-002", "SKU-00004", "2",  "10.00", "1.5", "20.00"),
    ("SAL-BAD-005", "",           "STO-003", "SKU-00005", "2",  "10.00", "0.0", "20.00"),
]


def main() -> None:
    con = duckdb.connect(str(DUCKDB_PATH))
    con.executemany(
        """
        insert into raw.sales
            (sale_id, sale_date, store_id, product_id, quantity,
             unit_price_eur, discount_pct, amount_eur, _source_file, _loaded_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, 'simulated-bad-data', now())
        """,
        BAD_ROWS,
    )
    total = con.execute("select count(*) from raw.sales").fetchone()[0]
    print(f"inserted {len(BAD_ROWS)} malformed rows; raw.sales now holds {total}")
    con.close()


if __name__ == "__main__":
    main()
