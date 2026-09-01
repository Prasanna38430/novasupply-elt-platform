# 0008: Retrieval over the contract corpus, and why it is hybrid

Status: accepted
Date: 2026-09-01

## Context

[ADR 0007](0007-local-llm-for-nl-to-sql.md) rejected retrieval for the NL-to-SQL panel:
seven mart tables fit in a prompt, so there was nothing to retrieve from. That still holds.

The contract corpus is a different shape. Twenty contracts and five amendments come to
roughly 13,000 tokens of French legal prose against about 700 for the schema, prefill alone
would take minutes per question, and the corpus grows with every supplier and every
renegotiation while the schema does not. The same project declining retrieval in one place
and adopting it in another is the point: the decision is about the corpus, not the fashion.

The corpus is also awkward on purpose. Amendments restate a clause without removing the
original, so superseded text stays in the index, fluent and plausible.

## Decision

Keep the index in DuckDB: vectors in a `FLOAT[768]` column, `array_cosine_similarity` to
rank them, no Chroma and no service to keep in sync. At 180 chunks a brute-force scan is
instant.

Retrieval is three things at once, because measurement showed no one of them is enough.
Accuracy@1 on a 120-question golden set, with the ten amended questions broken out:

| strategy | overall | amended clauses |
|---|---|---|
| semantic only | 90 % | 0 % |
| + supersession filter | 92 % | 20 % |
| + supplier filter | 96 % | 50 % |
| + BM25, fused | 99 % | 90 % |

1. **Supersession resolved at index time.** Each amendment names the clause it replaces in
   its own text, so that is parsed during indexing and the replaced chunk gets a
   `superseded_by` pointer. Similarity cannot discover this: the original states its term
   outright while the amendment only talks *about* changing one, so the obsolete clause is
   the better match and won all ten times.
2. **The entity is a filter, not a vector.** The contracts are near-identical boilerplate
   differing by a name and a few figures, and similarity measures topical similarity, so it
   cannot tell suppliers apart. A named supplier resolves to an id by lookup and becomes a
   `where` clause.
3. **BM25 alongside the vectors.** Embeddings treat "délai", "durée" and "préavis" as one
   idea of elapsed time, so delivery-window questions kept landing on the termination
   clause. DuckDB's `fts` extension supplies BM25 with a French stemmer.

The rankings are fused by reciprocal rank fusion rather than a weighted sum, because BM25
scores and cosine similarities share no scale and their ranges shift per query.

## Consequences

Retrieval returns the clause in force rather than merely a relevant one, and the dashboard
shows the clauses beside the answer, so a wrong answer is visibly wrong.

Two settings are load-bearing, and both were found by measuring rather than reasoning:

- **`RRF_K = 5`, not the conventional 60.** The literature's constant assumes pools of
  thousands; after the supplier filter a pool is about ten clauses, and 60 flattens ranks 1
  to 3 to within a rounding error. The correct clause was ranked second by *both*
  retrievers and still lost, 0.032258 against 0.032266. A test pins it below 10.
- **BM25 indexes `chunk_text` only.** Including the context header, which repeats the
  supplier name the metadata filter already handles, made the short preamble chunk win the
  keyword ranking on nearly every query. The preamble is excluded from the pool for the same
  reason: it names the parties and states no terms.

Without those two fixes, adding BM25 changed the score by nothing at all. That is the
cautionary half of this record: a hybrid retriever can be present, plausible and prominent
in a diagram while contributing nothing measurable, and the only reason we know it works is
the golden set.

The index is local to DuckDB, so the panel does not run against Snowflake. Snowflake has a
native `VECTOR` type and the design ports, but it is unbuilt and the dashboard says so
rather than failing. Scoring lives in `scripts/evaluate_retrieval.py`, which needs Ollama
and so cannot run in CI, for the same reason as extraction
([ADR 0009](0009-llm-steps-outside-ci.md)).
