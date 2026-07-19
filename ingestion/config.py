"""Shared configuration for the NovaSupply data generators.

The volumes are deliberately small so the whole dataset regenerates in seconds and
stays comfortable in DuckDB. Everything runs off one seed, so a given version of the
code always produces the same data.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Where raw files land. Mirrors the eventual S3 layout; overridable via .env.
RAW_DATA_DIR = Path(os.getenv("RAW_DATA_DIR", "data/raw"))

# One seed makes every generator reproducible.
SEED = 42

# Entity volumes.
N_SUPPLIERS = 20
N_PRODUCTS = 200
N_STORES = 8

# History window for the daily facts, inclusive. Roughly 90 days ending "yesterday".
HISTORY_DAYS = 90
HISTORY_END = date(2026, 7, 18)
HISTORY_START = HISTORY_END - timedelta(days=HISTORY_DAYS - 1)

# Product categories, French retail flavour.
CATEGORIES = ["Épicerie", "Frais", "Boissons", "Hygiène", "Surgelés"]

# Curated French store locations so region always matches the city.
STORE_LOCATIONS = [
    ("Paris", "Île-de-France"),
    ("Lyon", "Auvergne-Rhône-Alpes"),
    ("Marseille", "Provence-Alpes-Côte d'Azur"),
    ("Toulouse", "Occitanie"),
    ("Lille", "Hauts-de-France"),
    ("Bordeaux", "Nouvelle-Aquitaine"),
    ("Nantes", "Pays de la Loire"),
    ("Strasbourg", "Grand Est"),
]

# Where suppliers are based. Weighted toward France, some EU neighbours for lead-time
# variety (imports take longer, which later shows up as delivery delays).
SUPPLIER_COUNTRIES = [
    "France", "France", "France", "France",
    "Espagne", "Allemagne", "Italie", "Belgique",
]
