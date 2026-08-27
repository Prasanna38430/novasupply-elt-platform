"""Score contract retrieval against a golden set, one strategy at a time.

Retrieval either returns the clause that governs today or it does not, and the only way to
know which is to ask it questions whose right answer is already known. The golden set is
derived from the corpus itself rather than written by hand: for every supplier and every
topic, the correct chunk is that supplier's clause on that topic which nothing has
superseded. Twenty suppliers times six topics gives 120 questions.

The questions are phrased the way somebody would actually ask, not by echoing the article
headings, so a strategy cannot score well merely by matching the title back to itself. One
of them ("sous quel délai faut-il payer les factures") deliberately uses the word "délai"
about payment rather than delivery, because that near-miss is where naive similarity
search comes apart.

Three strategies are compared, each adding one constraint to the one before it, so the
report shows what every piece is actually worth rather than only the final number.

Needs Ollama running and the index built by ingestion/embed_documents.py:

    python scripts/evaluate_retrieval.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "ingestion"))

from config import DUCKDB_PATH  # noqa: E402
from embed_documents import embed  # noqa: E402

# (topic key matched against the article title, question template).
TOPICS = [
    ("délai de livraison", "Sous combien de jours {supplier} doit-il livrer une commande ?"),
    ("pénalités de retard", "Quelle pénalité s'applique si {supplier} livre en retard ?"),
    ("quantité minimale", "Quelle est la commande minimale acceptée par {supplier} ?"),
    ("conditions de paiement", "Sous quel délai faut-il payer les factures de {supplier} ?"),
    ("qualité", "Quel taux de produits non conformes {supplier} garantit-il ?"),
    ("durée", "Quel préavis faut-il respecter pour résilier le contrat avec {supplier} ?"),
]

STRATEGIES = {
    "semantic only": "",
    "+ supersession filter": "where superseded_by is null",
    "+ supplier filter": "where superseded_by is null and supplier_id = '{supplier_id}'",
}


def build_golden_set(con) -> list[dict]:
    """Expected answer per (supplier, topic): the clause on that topic still in force."""
    chunks = con.sql("""
        select chunk_id, supplier_id, supplier_name, article_title, superseded_by
        from search.contract_chunks
        where article_no > 0
    """).fetchdf()

    golden = []
    for supplier_id, rows in chunks.groupby("supplier_id"):
        supplier_name = rows["supplier_name"].iloc[0]
        for topic, template in TOPICS:
            live = rows[
                rows["article_title"].str.lower().str.contains(topic, regex=False)
                & rows["superseded_by"].isna()
            ]
            if len(live) != 1:
                # Ambiguous or missing: not a question with one defensible answer.
                continue
            golden.append({
                "supplier_id": supplier_id,
                "topic": topic,
                "question": template.format(supplier=supplier_name),
                "expected_chunk_id": live["chunk_id"].iloc[0],
                # Whether the right answer lives in an amendment. The aggregate hides
                # these; they are the ones that matter, because a miss here quotes terms
                # that are no longer in force rather than merely the wrong paragraph.
                "amended": "-A1#" in live["chunk_id"].iloc[0],
            })
    return golden


def top_chunk(con, vector, where: str) -> str:
    return con.execute(f"""
        select chunk_id from search.contract_chunks {where}
        order by array_cosine_similarity(embedding, {vector}::FLOAT[768]) desc
        limit 1
    """).fetchone()[0]


def main() -> None:
    # The topics are French and the Windows console defaults to cp1252, which turns every
    # accent into a replacement character.
    sys.stdout.reconfigure(encoding="utf-8")

    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    golden = build_golden_set(con)
    print(f"golden set: {len(golden)} questions\n")

    vectors = embed([item["question"] for item in golden])

    amended_total = sum(item["amended"] for item in golden)
    print(f"{'strategy':<24} {'overall':>12}   {'amended clauses':>16}   worst topic")
    print("-" * 78)

    for name, where in STRATEGIES.items():
        hits = amended_hits = 0
        misses: dict[str, int] = {}
        for item, vector in zip(golden, vectors):
            clause = where.format(supplier_id=item["supplier_id"])
            if top_chunk(con, vector, clause) == item["expected_chunk_id"]:
                hits += 1
                amended_hits += item["amended"]
            else:
                misses[item["topic"]] = misses.get(item["topic"], 0) + 1

        worst = max(misses.items(), key=lambda kv: kv[1]) if misses else ("-", 0)
        print(
            f"{name:<24} {hits:>4}/{len(golden)} ({100 * hits / len(golden):4.0f}%)"
            f"   {amended_hits:>7}/{amended_total} ({100 * amended_hits / amended_total:4.0f}%)"
            f"   {worst[0]} x{worst[1]}"
        )

    print(
        "\nThe overall column flatters the result: only "
        f"{amended_total} of {len(golden)} questions are governed by an amendment, and "
        "those are the ones where a miss quotes terms that no longer apply."
    )
    con.close()


if __name__ == "__main__":
    main()
