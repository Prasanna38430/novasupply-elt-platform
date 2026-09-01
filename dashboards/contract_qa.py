"""Answer questions about the supplier contracts, with the clause that says so.

Retrieval here is deliberately three things at once, because measurement showed no single
one of them is enough (scripts/evaluate_retrieval.py has the numbers):

  * a metadata filter, because the contracts are near-identical boilerplate differing
    mainly by a name and a few figures. Semantic similarity measures topical similarity,
    and every contract is topically identical, so naming a supplier in the question has to
    become a `where` clause rather than a hint the vector is left to infer;
  * a supersession filter, because an amendment replaces a clause without removing the
    original from the corpus. The superseded text states its term outright while the
    amendment only talks *about* replacing one, so the obsolete clause is the better
    semantic match and wins on score every time;
  * BM25 alongside the vectors, because embeddings treat "délai", "durée" and "préavis"
    as one idea of elapsed time. A question about the delivery window kept landing on the
    termination-notice clause, at near-identical scores.

The two rankings are combined by reciprocal rank fusion rather than by adding their
scores. BM25 scores and cosine similarities are not on a common scale and their ranges
shift with the query, so any weighted sum needs normalisation constants that quietly stop
being right; ranks need none.

The answer is generated from the retrieved clauses only, and the clauses are shown
alongside it, so a wrong answer is visibly wrong rather than merely confident.
"""
from __future__ import annotations

import re
from typing import Callable

import pandas as pd

import ollama

# Rank-fusion constant. The literature's 60 is tuned for candidate pools of thousands and
# is actively wrong here: once the supplier filter has run, a pool is about ten clauses,
# and k=60 flattens ranks 1, 2 and 3 to within a rounding error of each other. Measured on
# the golden set, the correct clause was losing to a tie broken by floating-point noise.
RRF_K = 5

# How many chunks reach the model. Few enough that the whole prompt stays small on a slow
# machine, plenty for a question that a single clause answers.
TOP_K = 4

ANSWER_PROMPT = """Réponds à la question en te fondant uniquement sur les extraits de \
contrat ci-dessous.

Règles :
- N'utilise que les extraits. Si la réponse ne s'y trouve pas, dis-le simplement.
- Cite la référence du document sur lequel tu t'appuies, par exemple (CTR-2026-0004-A1).
- Deux phrases maximum.

Extraits :
{context}

Question : {question}

Réponse :"""


def resolve_supplier(question: str, suppliers: pd.DataFrame) -> str | None:
    """Find which supplier a question is about, by name, and return their id.

    Deliberately a literal match rather than another model call: supplier names are a
    closed list of twenty that the warehouse already holds, so this is a lookup, and
    spending fifteen seconds of CPU generation to guess at one would be absurd. The
    longest match wins, so "Martinez SA" is not shadowed by a hypothetical "Martinez".
    """
    lowered = question.lower()
    matches = [
        row for row in suppliers.itertuples()
        if str(row.supplier_name).lower() in lowered
    ]
    if not matches:
        return None
    return max(matches, key=lambda row: len(str(row.supplier_name))).supplier_id


def _fts_available(con) -> bool:
    """Whether the BM25 index exists, so an older warehouse still answers, just worse."""
    try:
        con.execute("load fts")
        con.execute(
            "select fts_search_contract_chunks.match_bm25(chunk_id, 'test') "
            "from search.contract_chunks limit 1"
        )
        return True
    except Exception:  # noqa: BLE001 - absence of an index is not an error worth raising
        return False


def search(
    con,
    question: str,
    supplier_id: str | None = None,
    top_k: int = TOP_K,
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
) -> pd.DataFrame:
    """Return the clauses most likely to answer the question, current ones only."""
    embed_fn = embed_fn or ollama.embed
    vector = embed_fn([question])[0]

    # The preamble names the parties and states no terms, so it can never answer a
    # question about them. It is short, and BM25 rewards brevity, so leaving it in the
    # pool put it at the top of the keyword ranking for almost every query.
    where = ["superseded_by is null", "article_no > 0"]
    if supplier_id:
        where.append(f"supplier_id = '{supplier_id}'")
    clause = "where " + " and ".join(where)

    if _fts_available(con):
        # Rank by each method independently, then fuse. `full join` so a chunk found by
        # only one of the two still competes: the keyword and the vector hit lists overlap
        # far less than intuition suggests.
        sql = f"""
            with candidates as (
                select * from search.contract_chunks {clause}
            ),
            keyword as (
                select chunk_id,
                       row_number() over (order by score desc) as rank
                from (
                    select chunk_id,
                           fts_search_contract_chunks.match_bm25(chunk_id, ?) as score
                    from candidates
                )
                where score is not null
            ),
            semantic as (
                select chunk_id,
                       row_number() over (
                           order by array_cosine_similarity(embedding, ?::FLOAT[768]) desc
                       ) as rank
                from candidates
            ),
            fused as (
                select coalesce(k.chunk_id, s.chunk_id) as chunk_id,
                       coalesce(1.0 / ({RRF_K} + k.rank), 0)
                     + coalesce(1.0 / ({RRF_K} + s.rank), 0) as score
                from keyword k
                full join semantic s on s.chunk_id = k.chunk_id
            )
            select c.chunk_id, c.document_id, c.supplier_name, c.document_type, c.article_title,
                   c.chunk_text, c.effective_date, round(f.score, 5) as score
            from fused f
            join candidates c on c.chunk_id = f.chunk_id
            order by f.score desc
            limit {top_k}
        """
        return con.execute(sql, [question, vector]).fetchdf()

    return con.execute(
        f"""
        select chunk_id, document_id, supplier_name, document_type, article_title, chunk_text,
               effective_date,
               round(array_cosine_similarity(embedding, ?::FLOAT[768]), 5) as score
        from search.contract_chunks {clause}
        order by score desc
        limit {top_k}
        """,
        [vector],
    ).fetchdf()


def _context(clauses: pd.DataFrame) -> str:
    return "\n\n".join(
        f"[{row.document_id}] {row.article_title}\n{row.chunk_text}"
        for row in clauses.itertuples()
    )


def answer(
    con,
    question: str,
    suppliers: pd.DataFrame,
    on_token: Callable[[str], None] | None = None,
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
) -> tuple[str, pd.DataFrame, str | None]:
    """Retrieve, then answer from what was retrieved. Returns (answer, clauses, supplier)."""
    supplier_id = resolve_supplier(question, suppliers)
    clauses = search(con, question, supplier_id=supplier_id, embed_fn=embed_fn)
    if clauses.empty:
        return "Nothing in the contract corpus matches that question.", clauses, supplier_id

    text = ollama.stream_completion(
        ANSWER_PROMPT.format(context=_context(clauses), question=question),
        on_token=on_token,
        max_tokens=200,
        clean=lambda raw: re.sub(r"^```\w*\s*|```$", "", raw).strip(),
    )
    return text, clauses, supplier_id
