# 0008: Retrieval over the contract corpus, and why it is hybrid

Status: accepted
Date: 2026-09-01

## Context

[ADR 0007](0007-local-llm-for-nl-to-sql.md) rejected retrieval for the natural-language-to-SQL
panel, on the grounds that seven mart tables fit in a prompt and embedding them would be
infrastructure bought against a problem nobody had. That reasoning still holds, and this
decision does not overturn it.

The contract corpus is a different shape. Twenty master contracts and five amendments come
to roughly 13,000 tokens of French legal prose, against about 700 for the mart schema.
Prefill alone would take minutes per question on this machine, and the corpus grows with
every supplier and every renegotiation while the schema does not. That is where retrieval
starts earning its cost, and the contrast is the point: the same project both declines
retrieval and adopts it, for reasons that are about the corpus rather than about fashion.

The corpus was also built to be awkward on purpose. Amendments restate a clause without
removing the original, so the superseded text is still present, still fluent, and still a
perfectly plausible answer.

## Decision

Keep the index in DuckDB. Vectors live in a `FLOAT[768]` column and
`array_cosine_similarity` ranks them, so there is no Chroma, no pgvector and no service to
run or keep in sync. At 180 chunks a brute-force scan is instant; the `vss` extension's
HNSW index only pays off orders of magnitude further up.

Retrieval is three things at once, because measuring showed no one of them is enough. The
numbers below are accuracy@1 on a 120-question golden set derived from the corpus, with
the column that matters being the ten questions whose answer lives in an amendment:

| strategy | overall | amended clauses |
|---|---|---|
| semantic only | 90 % | 0 % |
| + supersession filter | 92 % | 20 % |
| + supplier filter | 96 % | 50 % |
| + BM25, fused (hybrid) | 99 % | 90 % |

1. **Supersession is resolved at index time, not query time.** Each amendment names the
   clause it replaces in its own text ("les stipulations de l'article 2 du contrat-cadre
   sont remplacées par"), so that sentence is parsed during indexing and the replaced chunk
   gets a `superseded_by` pointer. Similarity cannot discover this: the original states its
   term outright while the amendment only talks *about* changing one, so the obsolete
   clause is the better semantic match and won every time. Naive search returned a
   superseded clause for all ten amended questions.
2. **The entity is a filter, not a vector.** The contracts are near-identical boilerplate
   differing by a name and a few figures, so semantic similarity, which measures topical
   similarity, cannot tell suppliers apart. Naming a supplier in a question resolves to an
   id by literal lookup against `dim_suppliers` and becomes a `where` clause.
3. **BM25 alongside the vectors.** Embeddings treat "délai", "durée" and "préavis" as one
   idea of elapsed time, so questions about the delivery window kept landing on the
   termination-notice clause at near-identical scores. DuckDB's `fts` extension supplies
   BM25 with a French stemmer, so a question about "délais" still matches a clause saying
   "délai".

The two rankings are combined by reciprocal rank fusion rather than a weighted sum, because
BM25 scores and cosine similarities are not on a common scale and their ranges shift per
query, so any weighting needs normalisation constants that quietly stop being right.

## Consequences

Retrieval finds the clause in force rather than merely a relevant one, and the dashboard
shows the clauses beside the generated answer, so a wrong answer is visibly wrong instead
of merely confident.

Two settings are load-bearing and were both found by measurement rather than reasoning,
which is worth recording because both look like details and neither is:

- **`RRF_K = 5`, not the conventional 60.** The literature's constant assumes candidate
  pools of thousands. After the supplier filter a pool is about ten clauses, and 60
  flattens ranks 1, 2 and 3 to within a rounding error: the correct clause was ranked
  second by *both* retrievers and still lost, on a fused score of 0.032258 against
  0.032266. A test pins the constant below 10, because restoring a "standard" value would
  cost accuracy silently.
- **BM25 indexes `chunk_text` only, not the context header.** The header repeats the
  supplier name, which the metadata filter has already handled, so including it made the
  short preamble chunk win the keyword ranking on nearly every query. The preamble is
  excluded from the candidate pool for the same reason: it names the parties and states no
  terms, so it can never answer a question about them.

Adding BM25 without those two fixes changed the score by nothing at all, which is the
cautionary half of this record. A hybrid retriever can be present, plausible and
load-bearing in a diagram while contributing nothing measurable, and the only reason we
know it works now is the golden set.

The index is local to DuckDB, so the contract panel does not run against Snowflake.
Snowflake has a native `VECTOR` type and `VECTOR_COSINE_SIMILARITY` and the design ports
directly, but it is not built, and the dashboard says so rather than failing.

Retrieval quality is measured, not asserted: `scripts/evaluate_retrieval.py` scores every
strategy on demand. It needs Ollama and so cannot run in CI, which is the same constraint
that keeps extraction out of CI (see [ADR 0009](0009-llm-steps-outside-ci.md)).
