# 0007: Local Ollama for the NL-to-SQL panel, no RAG

Status: accepted
Date: 2026-08-11

## Context

The "Ask your data" panel turns a plain-language question into SQL against the marts.
Three shapes were on the table: a hosted API, a local model, and a retrieval layer over the
dbt docs.

A hosted API means a key, a recurring cost and a demo that breaks without internet. Cortex
would also burn trial credits earmarked for the cost work in [cost.md](../cost.md).

RAG was the tempting mistake. The mart schema is seven tables and about 700 characters.
There is nothing to retrieve *from* when the whole corpus fits in the prompt; retrieval
earns its cost at hundreds of documents, not at a fixed star schema.

## Decision

A local Ollama model with the whole schema in every prompt. Ollama caches the fixed prefix,
so re-sending it is nearly free: prefill measured 23 tokens/s cold against 1630 warm. That
is what makes the no-retrieval position hold in practice rather than only in principle.

The model is `qwen2.5-coder:3b`, not the planned `llama3.1:8b`. A hardware finding, not a
preference: on 8GB of RAM the larger model failed to load outright with
`unable to allocate CPU_REPACK buffer`.

Four things carry the accuracy, and at this size they matter more than the model does:

1. **Real DDL**, read from `information_schema`. The first version used a notation invented
   for the prompt, which the model had never seen and which silently omitted columns.
2. **A glossary** mapping business words to columns, pinning the two grain traps:
   `fct_inventory` is a daily snapshot, so "right now" needs `max(snapshot_date)`; and
   `is_late` is null on open orders. Both yield plausible wrong numbers rather than errors,
   which makes them worse than a crash.
3. **Worked examples**, because a 3B model pattern-matches more than it reasons.
4. **A repair loop**: on a database error, the failed SQL and the error go back for exactly
   one retry. A binder error naming the bad identifier is a near-perfect correction signal.

A guard (`nl_query.is_safe_select`) rejects anything that is not a bare `SELECT`/`WITH`,
carries a write keyword, or hides a second statement behind a semicolon. It is a denylist
rather than a parser deliberately: the model is told to emit one SELECT, so anything else is
already off-script. Results cap at 500 rows.

## Consequences

No key, no recurring cost, and it works offline; without Ollama the panel explains what to
install instead of breaking the dashboard.

The prompt work moved accuracy from unusable to dependable on the same model. Before it, a
question about stockouts joined the wrong fact table and used an undefined alias. After it,
five questions held out of the examples all returned correct SQL first time, both grain
traps handled unprompted, with the repair loop never firing.

The remaining trade-off is speed, and it is hardware. CPU-only inference on an i5-8250U with
no Ollama-capable GPU runs at about 5 tokens/second, because generation streams the whole
1.9GB of weights out of RAM per token. A warm question takes 15-25 seconds. Streaming and a
30-minute `keep_alive` make that liveable; nothing makes it fast.

Genuinely ambiguous or multi-step analytical questions are where 3B parameters is a real
ceiling. The fix there is a bigger model or a hosted one, still not retrieval, since the
schema is seven tables either way.
