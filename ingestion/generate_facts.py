"""Generate the three daily fact tables: sales, inventory_snapshots, purchase_orders.

This is a small inventory simulation rather than three independent random streams, so
the numbers tell one coherent story: demand draws stock down, low stock triggers a
replenishment order, and an unreliable supplier's late delivery is what leaves a store
out of stock. That causal chain is the whole point of the platform.

Run the dimension generator first, then:

    python ingestion/generate_facts.py
"""
from __future__ import annotations

import shutil
from datetime import timedelta

import numpy as np
import pandas as pd

from config import HISTORY_DAYS, HISTORY_END, HISTORY_START, RAW_DATA_DIR, SEED

# Demand multiplier by weekday (Mon=0 .. Sun=6). Busier Fri/Sat, quiet Sunday.
DOW_FACTOR = {0: 0.9, 1: 0.9, 2: 0.95, 3: 1.0, 4: 1.15, 5: 1.3, 6: 0.6}


def load_dimensions():
    base = RAW_DATA_DIR
    suppliers = pd.read_csv(base / "suppliers" / "suppliers.csv")
    products = pd.read_csv(base / "products" / "products.csv")
    stores = pd.read_csv(base / "stores" / "stores.csv")
    return suppliers, products, stores


def simulate(suppliers, products, stores, rng):
    days = [HISTORY_START + timedelta(days=d) for d in range(HISTORY_DAYS)]

    sup_lead = dict(zip(suppliers.supplier_id, suppliers.nominal_lead_time_days))
    sup_rel = dict(zip(suppliers.supplier_id, suppliers.reliability_score))

    # Per-product baseline daily demand per store. Lognormal so most SKUs are slow
    # movers and a few are popular.
    pop = rng.lognormal(mean=0.4, sigma=0.9, size=len(products))
    product_demand = dict(zip(products.product_id, np.clip(pop, 0.1, 20)))

    sales_rows, inventory_rows, po_rows = [], [], []
    sale_seq = po_seq = 0

    for store_id in stores.store_id:
        for prod in products.itertuples(index=False):
            pid = prod.product_id
            supplier_id = prod.supplier_id
            price = prod.unit_price_eur
            base = product_demand[pid]
            lead = int(sup_lead[supplier_id])
            reliability = float(sup_rel[supplier_id])

            mu_lead = base * lead
            reorder_point = int(np.ceil(mu_lead + 1.5 * np.sqrt(mu_lead)))
            order_up_to = reorder_point + int(np.ceil(base * 14))
            on_hand = order_up_to
            open_order = None  # dict(arrival, qty) or None; one outstanding at a time

            for d in days:
                # Receive an order that has arrived.
                if open_order and open_order["arrival"] <= d:
                    on_hand += open_order["qty"]
                    open_order = None

                # Demand and what we can actually sell.
                lam = base * DOW_FACTOR[d.weekday()]
                demand = int(rng.poisson(lam))
                sold = min(demand, on_hand)
                on_hand -= sold

                if sold > 0:
                    sale_seq += 1
                    discount = float(rng.choice([0.0, 0.0, 0.0, 0.0, 0.1, 0.2]))
                    amount = round(sold * price * (1 - discount), 2)
                    sales_rows.append(
                        {
                            "sale_id": f"SAL-{sale_seq:07d}",
                            "sale_date": d.isoformat(),
                            "store_id": store_id,
                            "product_id": pid,
                            "quantity": sold,
                            "unit_price_eur": price,
                            "discount_pct": discount,
                            "amount_eur": amount,
                        }
                    )

                in_transit = open_order["qty"] if open_order else 0
                inventory_rows.append(
                    {
                        "snapshot_date": d.isoformat(),
                        "store_id": store_id,
                        "product_id": pid,
                        "on_hand_qty": on_hand,
                        "reorder_point": reorder_point,
                        "in_transit_qty": in_transit,
                    }
                )

                # Replenish when low and nothing already on the way.
                if on_hand <= reorder_point and open_order is None:
                    po_seq += 1
                    ordered_qty = order_up_to - on_hand
                    promised = d + timedelta(days=lead)
                    # Unreliable suppliers slip past the promised date.
                    late_days = int(rng.integers(1, 8)) if rng.random() > reliability else 0
                    arrival = promised + timedelta(days=late_days)
                    # Occasionally a short shipment.
                    received = ordered_qty if rng.random() > 0.1 else int(ordered_qty * rng.uniform(0.6, 0.95))

                    open_order = {"arrival": arrival, "qty": received}

                    delivered = arrival <= HISTORY_END
                    po_rows.append(
                        {
                            "po_id": f"PO-{po_seq:06d}",
                            "order_date": d.isoformat(),
                            "supplier_id": supplier_id,
                            "product_id": pid,
                            "store_id": store_id,
                            "ordered_qty": ordered_qty,
                            "promised_date": promised.isoformat(),
                            "actual_delivery_date": arrival.isoformat() if delivered else "",
                            "received_qty": received if delivered else "",
                        }
                    )

    return (
        pd.DataFrame(sales_rows),
        pd.DataFrame(inventory_rows),
        pd.DataFrame(po_rows),
    )


def write_partitioned(df: pd.DataFrame, dataset: str, date_col: str) -> int:
    target = RAW_DATA_DIR / dataset
    if target.exists():
        shutil.rmtree(target)  # clear stale partitions from a previous run
    for day, chunk in df.groupby(date_col):
        out_dir = target / f"dt={day}"
        out_dir.mkdir(parents=True, exist_ok=True)
        chunk.to_csv(out_dir / f"{dataset}.csv", index=False, encoding="utf-8")
    return len(df)


def main() -> None:
    rng = np.random.default_rng(SEED)
    suppliers, products, stores = load_dimensions()
    sales, inventory, purchase_orders = simulate(suppliers, products, stores, rng)

    n_sales = write_partitioned(sales, "sales", "sale_date")
    n_inv = write_partitioned(inventory, "inventory", "snapshot_date")
    n_po = write_partitioned(purchase_orders, "purchase_orders", "order_date")

    print(f"sales           {n_sales:>7} rows across {sales.sale_date.nunique()} partitions")
    print(f"inventory       {n_inv:>7} rows across {inventory.snapshot_date.nunique()} partitions")
    print(f"purchase_orders {n_po:>7} rows across {purchase_orders.order_date.nunique()} partitions")


if __name__ == "__main__":
    main()
