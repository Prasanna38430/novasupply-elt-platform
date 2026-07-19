"""Generate the three dimension tables: suppliers, products, stores.

These are current-state files with no date partition, because they change slowly. Run
this before the fact generators, which reference the IDs produced here.

    python ingestion/generate_dimensions.py
"""
from __future__ import annotations

import random

import pandas as pd
from faker import Faker

from config import (
    CATEGORIES,
    HISTORY_START,
    N_PRODUCTS,
    N_STORES,
    N_SUPPLIERS,
    RAW_DATA_DIR,
    SEED,
    STORE_LOCATIONS,
    SUPPLIER_COUNTRIES,
)

fake = Faker("fr_FR")


def _seed() -> None:
    random.seed(SEED)
    Faker.seed(SEED)


def generate_suppliers() -> pd.DataFrame:
    rows = []
    for i in range(1, N_SUPPLIERS + 1):
        country = random.choice(SUPPLIER_COUNTRIES)
        # Domestic suppliers ship quicker than imports.
        base_lead = 4 if country == "France" else 10
        rows.append(
            {
                "supplier_id": f"SUP-{i:04d}",
                "supplier_name": fake.company(),
                "country": country,
                "city": fake.city(),
                "nominal_lead_time_days": base_lead + random.randint(0, 10),
                "reliability_score": round(random.uniform(0.75, 0.99), 2),
                "valid_from": HISTORY_START.isoformat(),
            }
        )
    return pd.DataFrame(rows)


def generate_products(suppliers: pd.DataFrame) -> pd.DataFrame:
    supplier_ids = suppliers["supplier_id"].tolist()
    rows = []
    for i in range(1, N_PRODUCTS + 1):
        category = random.choice(CATEGORIES)
        unit_cost = round(random.uniform(0.5, 40.0), 2)
        # Retail margin between 25% and 90% over cost.
        unit_price = round(unit_cost * random.uniform(1.25, 1.9), 2)
        rows.append(
            {
                "product_id": f"SKU-{i:05d}",
                "product_name": f"{category} {fake.word().capitalize()}",
                "category": category,
                "supplier_id": random.choice(supplier_ids),
                "unit_cost_eur": unit_cost,
                "unit_price_eur": unit_price,
            }
        )
    return pd.DataFrame(rows)


def generate_stores() -> pd.DataFrame:
    rows = []
    for i, (city, region) in enumerate(STORE_LOCATIONS[:N_STORES], start=1):
        rows.append(
            {
                "store_id": f"STO-{i:03d}",
                "store_name": f"NovaSupply {city}",
                "city": city,
                "region": region,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    _seed()
    suppliers = generate_suppliers()
    products = generate_products(suppliers)
    stores = generate_stores()

    for name, df in [("suppliers", suppliers), ("products", products), ("stores", stores)]:
        out_dir = RAW_DATA_DIR / name
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{name}.csv"
        df.to_csv(out_path, index=False, encoding="utf-8")
        print(f"wrote {len(df):>4} rows -> {out_path}")


if __name__ == "__main__":
    main()
