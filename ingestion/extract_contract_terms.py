"""Read the commercial terms out of each contract and land them as a dbt seed.

This is the step that turns prose into columns. A model reads each document and returns
the delivery window, the penalty rate and the rest as JSON; everything downstream then
treats those as ordinary warehouse fields and never looks at the text again.

The output is committed as a dbt seed rather than written straight into `raw`, for one
practical reason: CI has no Ollama and no GPU, and a mart that depended on a live model
call would turn every build red. Extraction is expensive and its input barely changes, so
the result is a reviewed, version-controlled artefact and the model runs only when the
contracts do change. Re-running skips documents already in the seed unless --force is
passed.

Accuracy is measured, not assumed. The generator wrote an answer key next to the corpus
and this script scores against it, per field, so "the extraction works" is a number rather
than an impression. Amendments are scored only on the clauses they actually restate, since
a document cannot be faulted for staying silent about terms it never touched.

Needs Ollama running:

    python ingestion/extract_contract_terms.py [--force]
"""
from __future__ import annotations

import argparse
import json
import sys

import pandas as pd
import requests

from config import PROJECT_ROOT, RAW_DATA_DIR

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5-coder:3b"
KEEP_ALIVE = "30m"
REQUEST_TIMEOUT = 600

CONTRACTS_DIR = RAW_DATA_DIR / "contracts"
SEED_PATH = PROJECT_ROOT / "dbt" / "seeds" / "contract_terms.csv"

FIELDS = [
    "lead_time",
    "penalty_rate",
    "penalty_cap",
    "min_order_qty",
    "payment_terms",
    "quality_tolerance",
    "notice_period",
]

# An amendment restates only the clauses it replaces, so those are the only ones it can
# fairly be scored on.
AMENDMENT_FIELDS = ["lead_time", "penalty_rate", "penalty_cap"]

# Counts of days, units and whole percent. Written as integers because the seed is meant
# to be read and reviewed in a diff, and a lead time of "4.0 days" reads like a mistake.
# Rates stay floating point: a penalty really can be 1,3 % per day.
INTEGER_FIELDS = ["lead_time", "penalty_cap", "min_order_qty", "payment_terms", "notice_period"]

PROMPT_TEMPLATE = """Tu extrais les conditions commerciales d'un contrat fournisseur.

Réponds uniquement en JSON, avec exactement ces clés :
- lead_time : délai de livraison maximum, en jours
- penalty_rate : pénalité de retard, en % par jour
- penalty_cap : plafond des pénalités, en % de la commande
- min_order_qty : quantité minimale de commande, en unités
- payment_terms : délai de paiement des factures, en jours
- quality_tolerance : taux de non-conformité toléré, en %
- notice_period : préavis de résiliation, en jours

Règles :
- Les nombres décimaux sont écrits à la française (1,3 signifie 1.3). Renvoie-les au format \
JSON, avec un point.
- Renvoie null pour toute valeur que le document ne mentionne pas. N'invente rien.
- Aucun texte hors du JSON.

Contrat :
{document}

JSON :"""


def _to_number(value):
    """Coerce whatever the model returned into a number, or None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace(",", ".").replace("%", "").strip()
    if not text or text.lower() in {"null", "none", "n/a"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def extract(document: str) -> dict:
    """Ask the model for one document's terms. JSON mode keeps the reply parseable."""
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "prompt": PROMPT_TEMPLATE.format(document=document),
            "stream": False,
            "format": "json",
            "keep_alive": KEEP_ALIVE,
            "options": {"temperature": 0},
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    try:
        payload = json.loads(response.json()["response"])
    except json.JSONDecodeError:
        payload = {}
    return {field: _to_number(payload.get(field)) for field in FIELDS}


def score(extracted: pd.DataFrame) -> None:
    """Compare against the answer key the generator left, field by field."""
    truth_path = CONTRACTS_DIR / "_ground_truth.csv"
    if not truth_path.exists():
        print("no ground truth found, skipping scoring")
        return

    truth = pd.read_csv(truth_path).set_index("document_id")
    merged = extracted.set_index("document_id")

    print(f"\n{'field':<20} {'correct':>10}")
    print("-" * 32)
    totals = {"hit": 0, "n": 0}
    for field in FIELDS:
        hits = seen = 0
        for document_id, row in merged.iterrows():
            if document_id not in truth.index:
                continue
            is_amendment = "-A1" in str(document_id)
            if is_amendment and field not in AMENDMENT_FIELDS:
                continue
            seen += 1
            expected = float(truth.loc[document_id, field])
            actual = row[field]
            if actual is not None and abs(float(actual) - expected) < 1e-6:
                hits += 1
        totals["hit"] += hits
        totals["n"] += seen
        print(f"{field:<20} {hits:>4}/{seen:<4} {100 * hits / seen:5.0f}%")
    print("-" * 32)
    print(f"{'overall':<20} {totals['hit']:>4}/{totals['n']:<4} "
          f"{100 * totals['hit'] / totals['n']:5.0f}%")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="re-extract every document")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    catalogue = pd.read_csv(CONTRACTS_DIR / "catalogue.csv")
    done = {}
    if SEED_PATH.exists() and not args.force:
        cached = pd.read_csv(SEED_PATH)
        done = {row.document_id: row._asdict() for row in cached.itertuples(index=False)}
        print(f"{len(done)} document(s) already extracted, skipping those")

    rows = []
    for position, doc in enumerate(catalogue.itertuples(index=False), start=1):
        if doc.document_id in done:
            rows.append(done[doc.document_id])
            continue
        text = (CONTRACTS_DIR / doc.file_name).read_text(encoding="utf-8")
        print(f"  [{position:>2}/{len(catalogue)}] {doc.document_id}", flush=True)
        rows.append({
            "document_id": doc.document_id,
            "supplier_id": doc.supplier_id,
            **extract(text),
        })

    extracted = pd.DataFrame(rows)[["document_id", "supplier_id", *FIELDS]]
    # Nullable Int64 rather than plain int: an amendment leaves most of these empty.
    for field in INTEGER_FIELDS:
        extracted[field] = extracted[field].astype("Int64")
    SEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    extracted.to_csv(SEED_PATH, index=False, encoding="utf-8")
    print(f"\nwrote {len(extracted)} rows -> {SEED_PATH}")

    score(extracted)


if __name__ == "__main__":
    main()
