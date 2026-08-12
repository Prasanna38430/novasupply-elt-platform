# 0007: Local Ollama for the NL-to-SQL panel, no RAG

Status: accepted
Date: 2026-08-11

## Context

The dashboard's "Ask your data" panel turns a plain-language question into SQL against
the mart layer. Three shapes were on the table: (1) a hosted API (OpenAI, or Snowflake
Cortex now that Terraform provisions Snowflake anyway), (2) a local model via Ollama, and
(3) a retrieval layer (embed the dbt docs in a vector store, retrieve relevant schema
chunks per question, feed them to the model — the standard RAG pattern).

A hosted API means an API key, a recurring cost, and a demo that breaks without internet.
Cortex specifically also has region caveats against the project's `eu-west-3` Snowflake
setup and burns trial credits already earmarked for the cost-report work in
[docs/cost.md](../cost.md).

RAG was the more tempting mistake. The mart layer is seven tables
([_marts__models.yml](../../dbt/models/marts/_marts__models.yml)) with stable, well-described
columns — the entire schema fits in about 700 characters. Embedding that into a vector
store, retrieving top-k chunks, and re-ranking them is solving a retrieval problem that
does not exist yet: there is nothing to retrieve *from* when the whole corpus fits in the
prompt directly. RAG earns its cost at hundreds of documents or a schema that changes
per-query; a fixed seven-table star schema is not that.

## Decision

Use a local Ollama model with the whole schema in the prompt on every call — no vector
store, no retrieval step, no LangChain. Ollama caches the fixed prompt prefix, so
re-sending the schema every time is close to free: measured prefill went from 23 tokens/s
on the first call to 1630 tokens/s once warm. That is what makes the no-retrieval position
hold up in practice and not just in principle.

The model is `qwen2.5-coder:3b`, not the originally-planned `llama3.1:8b`. That was a
hardware finding, not a preference: the development machine has 8GB of total RAM, and
`llama3.1:8b` (needs roughly 5.5GB free to load) failed with
`unable to allocate CPU_REPACK buffer` the first time it actually ran. A 3B model tuned
for code rather than general chat both fits the memory budget and drafts SQL at least as
well for this narrow a task — general chat ability that a bigger model would offer is not
being used here anyway.

Four things carry the accuracy, and they matter more than model size at this scale:

1. **The schema is real DDL**, generated from `information_schema` against the built
   warehouse rather than written by hand. The first version used a compact notation
   invented for this file; the model had seen millions of `CREATE TABLE` statements in
   training and none of that notation, and it also silently omitted columns (`is_late`,
   `in_transit_qty`, `reorder_point`) that questions then needed.
2. **A glossary maps business words to columns** ("stockout" -> `is_stockout`, "late" ->
   `is_late`) and pins the two grain traps: `fct_inventory` is a daily snapshot, so any
   "right now" question must filter to `max(snapshot_date)` or it counts each SKU up to 90
   times; and `is_late`/`delay_days` are null on open orders, so delivery-performance
   questions must filter `is_open = false`. Both produce plausible, wrong numbers rather
   than errors, which makes them worse than a crash.
3. **Worked examples**, because a 3B model pattern-matches far more than it reasons.
4. **A repair loop.** When the warehouse rejects the SQL, the error and the failed query go
   back to the model for exactly one retry. Nearly everything this size of model gets wrong
   is an alias or column slip, and a binder error naming the offending identifier is a
   near-perfect correction signal.

The model must reply with a single SQL statement; a guard (`nl_query.is_safe_select`)
rejects anything that is not a bare `SELECT`/`WITH`, that contains a write or DDL keyword,
or that carries a second statement behind a semicolon, before the query function ever sees
it. Results are capped at 500 rows. The guard is a denylist rather than a parser
deliberately: the model is instructed to emit one SELECT, so anything carrying a write
keyword is already off-script and worth refusing outright instead of reasoning about.
[tests/test_nl_query.py](../../tests/test_nl_query.py) covers it in CI, stubbing the model
out so it needs no Ollama.

## Consequences

Zero recurring cost, no API key, and the demo works offline — the panel degrades to a
clear "install Ollama" message (`OllamaUnavailable`) rather than a stack trace when the
server is not running, so the rest of the dashboard is unaffected either way.

Accuracy went from unusable to dependable on the strength of the prompt work alone, on the
same model. Before it: asked "which category has the most stockouts this month?", the model
joined `fct_purchase_orders` instead of `fct_inventory` and referenced an alias it never
defined; a second question failed the same way. After it: five questions deliberately held
out of the examples — top products by revenue in a named region, average days of cover by
category, open orders per supplier, stockout rate by store, revenue per month — all
returned correct SQL on the first attempt, with both grain traps handled unprompted. The
repair loop did not have to fire.

The remaining trade-off is speed, and it is hardware, not software. The development machine
is an i5-8250U with no Ollama-capable GPU (the Radeon R7 M460 predates ROCm support and
Intel integrated graphics are unsupported on Windows), so inference is CPU-only at about 5
tokens/second. Token generation is memory-bandwidth-bound — every token streams the whole
1.9GB of weights out of RAM — which puts a warm question at 15-25 seconds and the first
question after an idle period at closer to 40. Two things make that liveable rather than
fixable: the response is streamed, so the query visibly takes shape instead of leaving a
blank spinner, and `keep_alive` holds the model in memory for 30 minutes so a demo does not
pay the ~9 second reload between questions.

Where this would still lose to a hosted model is genuinely ambiguous or multi-step
analytical questions, where 3B parameters is a real ceiling. If that becomes the point
rather than the pattern, the fix is a bigger model (RAM permitting) or a hosted one — still
not retrieval, since the schema is seven tables either way.
