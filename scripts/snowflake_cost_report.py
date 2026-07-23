"""Report what NovaSupply is costing in Snowflake.

Reads ACCOUNT_USAGE for warehouse credit consumption and storage, so the numbers are
Snowflake's own billing view rather than an estimate. Run it after a dbt build to see what
that build actually cost.

ACCOUNT_USAGE needs ACCOUNTADMIN and lags real time by up to about 45 minutes, so a run
immediately after a build may not show it yet. WAREHOUSE_LOAD_HISTORY is closer to live.

    python scripts/snowflake_cost_report.py
"""
from __future__ import annotations

import os
from pathlib import Path

import snowflake.connector
from dotenv import load_dotenv

# Standard Edition on-demand list price in EUR at the time of writing. Credits are the
# real unit; this only turns them into a number people recognise.
EUR_PER_CREDIT = 2.75


def main() -> None:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

    con = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role="ACCOUNTADMIN",
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        login_timeout=60,
    )
    cur = con.cursor()

    print("=" * 62)
    print("NovaSupply - Snowflake cost report")
    print("=" * 62)

    cur.execute("""
        select warehouse_name,
               round(sum(credits_used), 4) as credits,
               count(*) as metering_periods
        from snowflake.account_usage.warehouse_metering_history
        group by warehouse_name
        order by credits desc
    """)
    rows = cur.fetchall()
    print("\ncredits by warehouse (account lifetime)")
    total = 0.0
    for name, credits, periods in rows:
        credits = float(credits or 0)
        total += credits
        marker = "  <-- NovaSupply" if name == os.environ.get("SNOWFLAKE_WAREHOUSE") else ""
        print(f"  {name:<28} {credits:>9.4f} cr  ({periods} periods){marker}")
    print(f"  {'TOTAL':<28} {total:>9.4f} cr  ~ EUR {total * EUR_PER_CREDIT:,.2f}")

    cur.execute("""
        select round(sum(credits_used), 4)
        from snowflake.account_usage.warehouse_metering_history
        where warehouse_name = %s
    """, (os.environ.get("SNOWFLAKE_WAREHOUSE"),))
    nova = float(cur.fetchone()[0] or 0)
    print(f"\nNovaSupply warehouse only: {nova:.4f} credits ~ EUR {nova * EUR_PER_CREDIT:,.2f}")

    cur.execute("""
        select round(avg(storage_bytes) / power(1024, 3), 4),
               round(avg(stage_bytes)   / power(1024, 3), 4)
        from snowflake.account_usage.storage_usage
        where usage_date >= dateadd(day, -7, current_date())
    """)
    row = cur.fetchone()
    if row and row[0] is not None:
        print(f"storage (7-day avg)      : {float(row[0]):.4f} GB table, {float(row[1] or 0):.4f} GB stage")

    # The single most effective cost control, so worth showing it is actually set.
    cur.execute("show warehouses like %s", (os.environ.get("SNOWFLAKE_WAREHOUSE"),))
    rows = cur.fetchall()
    cols = [d[0].lower() for d in cur.description]
    if rows:
        r = rows[0]
        print(f"\nwarehouse settings")
        print(f"  size          : {r[cols.index('size')]}")
        print(f"  auto_suspend  : {r[cols.index('auto_suspend')]}s")
        print(f"  state         : {r[cols.index('state')]}")

    cur.execute("""
        select query_type, count(*) n, round(sum(total_elapsed_time) / 1000.0, 1) seconds
        from snowflake.account_usage.query_history
        where warehouse_name = %s
        group by query_type
        order by seconds desc nulls last
        limit 5
    """, (os.environ.get("SNOWFLAKE_WAREHOUSE"),))
    rows = cur.fetchall()
    if rows:
        print("\nbusiest query types on this warehouse")
        for qtype, n, seconds in rows:
            print(f"  {qtype:<22} {n:>5} queries  {float(seconds or 0):>8.1f}s total")

    con.close()
    print()


if __name__ == "__main__":
    main()
