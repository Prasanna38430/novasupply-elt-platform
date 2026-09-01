# 0009: Keep the model-dependent steps out of CI and out of the DAG

Status: accepted
Date: 2026-09-01

## Context

Three steps need a local LLM: embedding the contract chunks, extracting commercial terms
from the prose, and scoring retrieval. Neither place that would normally run them can.

CI runs on a GitHub-hosted runner with no Ollama and no GPU; a model would mean pulling
about 2GB per job onto a build that finishes in a hundred seconds. Airflow runs in Docker
under a 2GB container budget, which is already why the executor is LocalExecutor rather
than Celery ([ADR 0005](0005-airflow-localexecutor.md)) — `qwen2.5-coder:3b` is 1.9GB of
weights before the runtime around it.

The awkward part is that `dim_supplier_contracts` and `fct_contract_compliance` are
ordinary dbt models, and `dbt build` has to work in CI like everything else. A mart
depending on a live model call would turn every build red.

## Decision

Split the work by whether a model is needed, and let the boundary fall on a file.

**In CI and in the DAG:** generating the corpus. Seeded Python, no model, deterministic to
the byte, and it belongs beside the other generators.

**In neither:** embedding, extraction and scoring. These run by hand when the contracts
change. Extraction writes `dbt/seeds/contract_terms.csv`, a committed dbt seed, so the
models downstream read a version-controlled table; embedding writes into the local DuckDB
file, which is gitignored and rebuilt on demand because only the dashboard reads it.

The seed is the load-bearing part, and it is not merely a workaround. Extraction takes
about twenty minutes on CPU, its input is nearly static, and its output is twenty-five rows
of numbers a human can read in a diff. The figures a mart is built on should be inspectable
and should change only when somebody meant them to. Re-running skips documents already in
the seed unless `--force` is passed.

## Consequences

CI stays fast and hermetic. It regenerates the corpus from the seed value, and because
generation is deterministic the fresh catalogue joins cleanly against the committed terms.
That join is what this arrangement risks, so it is left to fail loudly rather than papered
over with an outer join.

The cost is honesty about what is automated. The nightly DAG does not refresh contract
terms, and a new contract does not reach the warehouse until somebody runs extraction and
commits the result. For a corpus that changes a few times a year that is reasonable; for a
daily one it would not be, and the fix would be a worker with a model on it rather than a
bigger Airflow container.

Retrieval scoring lives in `scripts/` for the same reason: a quality check that needs a
model cannot gate a build. What CI *can* test is the logic around the model, and that is
covered — the read-only SQL gate, the French decimal parsing, supplier resolution and the
fusion constant.
