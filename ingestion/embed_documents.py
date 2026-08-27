"""Chunk the supplier contracts and embed them into a searchable table.

The retrieval index lives in the warehouse itself. DuckDB stores the vectors as a
FLOAT[N] column and `array_cosine_similarity` ranks them, so there is no Chroma, no
pgvector and no separate service to run or keep in sync. At this corpus size a brute-force
scan over a couple of hundred rows is instant; the `vss` extension's HNSW index only starts
paying for itself several orders of magnitude further up, and adding it now would be
infrastructure bought against a problem nobody has.

Chunks are split on article boundaries rather than every N characters. Contracts are
already divided into the units a question is actually about ("what is the delivery
window", "what is the penalty rate"), so honouring that structure keeps whole clauses
intact instead of cutting them mid-sentence.

Each chunk is embedded with a context header naming the supplier, the document and its
effective date. Without it, article 2 of all twenty contracts is close to identical text
and the vectors cluster on "delivery window clause" while telling nothing apart by
supplier. The header is what makes a chunk answerable on its own.

Run the document generator first, and have Ollama running, then:

    python ingestion/embed_documents.py
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import duckdb
import pandas as pd
import requests

from config import DUCKDB_PATH, RAW_DATA_DIR

OLLAMA_URL = "http://localhost:11434/api/embed"
EMBED_MODEL = "nomic-embed-text"

# Small batches: the embedding model shares 8GB with everything else on this machine.
BATCH_SIZE = 16
REQUEST_TIMEOUT = 300

CONTRACTS_DIR = RAW_DATA_DIR / "contracts"

# "Article 12 - Titre" starts a clause. Everything before the first one is the preamble.
ARTICLE_RE = re.compile(r"^Article (\d+) - (.+)$", re.MULTILINE)

# An amendment names the clause it replaces: "les stipulations de l'article 2 du
# contrat-cadre sont remplacées par...". That sentence is the only thing linking the two
# documents, and reading it here is what lets a query filter superseded text out.
SUPERSEDES_ARTICLE_RE = re.compile(r"l'article (\d+) du contrat-cadre", re.IGNORECASE)


class OllamaUnavailable(RuntimeError):
    """The local Ollama server isn't reachable."""


def split_articles(text: str) -> list[tuple[int, str, str]]:
    """Split a document into (article number, title, body), preamble first as article 0."""
    matches = list(ARTICLE_RE.finditer(text))
    if not matches:
        return [(0, "Document", text.strip())]

    chunks = [(0, "Préambule", text[: matches[0].start()].strip())]
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[match.start():end].strip()
        chunks.append((int(match.group(1)), match.group(2).strip(), body))
    return chunks


def _context_header(row: pd.Series) -> str:
    """What the chunk needs to say about itself to be answerable out of context."""
    kind = "Avenant" if row["document_type"] == "avenant" else "Contrat-cadre"
    header = (
        f"{kind} {row['document_id']} - fournisseur {row['supplier_name']} "
        f"({row['supplier_id']}), en vigueur au {row['effective_date']}"
    )
    if isinstance(row["supersedes"], str) and row["supersedes"]:
        header += f", remplace des clauses du contrat {row['supersedes']}"
    return header


def build_chunks() -> pd.DataFrame:
    catalogue = pd.read_csv(CONTRACTS_DIR / "catalogue.csv")
    suppliers = pd.read_csv(RAW_DATA_DIR / "suppliers" / "suppliers.csv")
    catalogue = catalogue.merge(
        suppliers[["supplier_id", "supplier_name"]], on="supplier_id", how="left"
    )

    rows = []
    for _, doc in catalogue.iterrows():
        text = (CONTRACTS_DIR / doc["file_name"]).read_text(encoding="utf-8")
        header = _context_header(doc)
        for article_no, title, body in split_articles(text):
            if not body:
                continue
            rows.append({
                "chunk_id": f"{doc['document_id']}#{article_no}",
                "document_id": doc["document_id"],
                "supplier_id": doc["supplier_id"],
                "supplier_name": doc["supplier_name"],
                "document_type": doc["document_type"],
                "supersedes": doc["supersedes"],
                "effective_date": doc["effective_date"],
                "article_no": article_no,
                "article_title": title,
                "context_header": header,
                "chunk_text": body,
                "superseded_by": None,
            })
    return _mark_superseded(pd.DataFrame(rows))


def _mark_superseded(chunks: pd.DataFrame) -> pd.DataFrame:
    """Point each replaced clause at the amendment clause that replaced it.

    Resolved once here rather than at query time, because similarity cannot discover it:
    the original states its clause outright while the amendment only talks *about*
    changing one, so the superseded text is the better semantic match for a question about
    the term and wins on score every time. Filtering on this column is what makes a search
    return what is in force rather than what merely reads relevant.
    """
    by_key = {(c.document_id, c.article_no): c.Index for c in chunks.itertuples()}

    for amendment in chunks[chunks["document_type"] == "avenant"].itertuples():
        if amendment.article_no == 0:
            continue
        match = SUPERSEDES_ARTICLE_RE.search(amendment.chunk_text)
        if not match:
            continue
        target = by_key.get((amendment.supersedes, int(match.group(1))))
        if target is not None:
            chunks.at[target, "superseded_by"] = amendment.chunk_id
    return chunks


def embed(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts with the local model."""
    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": EMBED_MODEL, "input": texts},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.exceptions.ConnectionError as exc:
        raise OllamaUnavailable(
            f"Can't reach Ollama at {OLLAMA_URL}. Start it, run "
            f"`ollama pull {EMBED_MODEL}` once, then retry."
        ) from exc
    return response.json()["embeddings"]


def embed_chunks(chunks: pd.DataFrame) -> list[list[float]]:
    vectors: list[list[float]] = []
    # Embedding is a single forward pass per chunk, not token-by-token generation, so this
    # runs in a couple of minutes on CPU where drafting the same volume of text would not.
    for start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks.iloc[start:start + BATCH_SIZE]
        texts = [
            f"{row.context_header}\n\n{row.chunk_text}" for row in batch.itertuples()
        ]
        vectors.extend(embed(texts))
        print(f"  embedded {min(start + BATCH_SIZE, len(chunks)):>4} / {len(chunks)}")
    return vectors


def main() -> None:
    chunks = build_chunks()
    print(f"chunked {chunks['document_id'].nunique()} documents into {len(chunks)} chunks")

    vectors = embed_chunks(chunks)
    dimensions = len(vectors[0])
    chunks["embedding"] = vectors
    chunks["_embedded_at"] = datetime.now(timezone.utc)

    con = duckdb.connect(str(DUCKDB_PATH))
    con.execute("create schema if not exists search")
    con.register("chunks_df", chunks)
    # The width is read off the model's own output rather than hardcoded, so swapping the
    # embedding model does not silently write vectors of the wrong shape.
    con.execute(
        f"""
        create or replace table search.contract_chunks as
        select * exclude (embedding),
               embedding::FLOAT[{dimensions}] as embedding
        from chunks_df
        """
    )
    total = con.execute("select count(*) from search.contract_chunks").fetchone()[0]
    con.close()

    print(f"wrote search.contract_chunks  {total:>4} rows, {dimensions}-dim vectors")
    print(f"warehouse: {DUCKDB_PATH}")


if __name__ == "__main__":
    main()
