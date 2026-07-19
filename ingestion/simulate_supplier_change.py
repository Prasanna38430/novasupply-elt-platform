"""Apply an operational change to one supplier so the SCD2 snapshot has history to track.

Real supplier terms drift: contracts get renegotiated, reliability changes. Our seeded
generator produces the same suppliers every run, so to demonstrate Type-2 history we
apply a single documented change here. SUP-0002 negotiates a shorter lead time and
improves its reliability.

Sequence to see SCD2 in action:

    python ingestion/load_raw.py
    (cd dbt && dbt snapshot)          # version 1 captured
    python ingestion/simulate_supplier_change.py
    (cd dbt && dbt snapshot)          # SUP-0002 gets a second version
"""
from __future__ import annotations

from datetime import date

import duckdb

from config import DUCKDB_PATH

CHANGE = {
    "supplier_id": "SUP-0002",
    "nominal_lead_time_days": 5,   # renegotiated down from 7
    "reliability_score": 0.90,     # improved from 0.78
}


def main() -> None:
    con = duckdb.connect(str(DUCKDB_PATH))
    cols = "supplier_id, nominal_lead_time_days, reliability_score, valid_from"
    before = con.execute(
        f"select {cols} from raw.suppliers where supplier_id = ?",
        [CHANGE["supplier_id"]],
    ).fetchdf()
    print("before:")
    print(before.to_string(index=False))

    # raw columns are text (faithful landing layer), so bind values as strings.
    con.execute(
        """
        update raw.suppliers
        set nominal_lead_time_days = ?,
            reliability_score = ?,
            valid_from = ?
        where supplier_id = ?
        """,
        [
            str(CHANGE["nominal_lead_time_days"]),
            str(CHANGE["reliability_score"]),
            date.today().isoformat(),
            CHANGE["supplier_id"],
        ],
    )

    after = con.execute(
        f"select {cols} from raw.suppliers where supplier_id = ?",
        [CHANGE["supplier_id"]],
    ).fetchdf()
    print("after:")
    print(after.to_string(index=False))
    con.close()


if __name__ == "__main__":
    main()
