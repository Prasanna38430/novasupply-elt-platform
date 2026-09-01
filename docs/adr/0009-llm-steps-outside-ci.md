# 0009: Keep the model-dependent steps out of CI and out of the DAG

Status: accepted
Date: 2026-09-01

## Context

Three steps in this project need a local LLM: embedding the contract chunks, extracting
commercial terms from the contract prose, and scoring retrieval against the golden set.
Neither of the two places that would normally run them can.

CI runs on a GitHub-hosted runner with no Ollama and no GPU. Installing a model there
would mean pulling roughly 2GB per job on a build that currently finishes in a hundred
seconds, for a step whose input changes only when a contract does.

Airflow runs in Docker on a machine whose container budget is 2GB, which is already why
the executor is LocalExecutor rather than Celery ([ADR 0005](0005-airflow-localexecutor.md)).
`qwen2.5-coder:3b` alone is 1.9GB of weights before the runtime around it. There is no
room, and pretending otherwise would produce a DAG that only runs on one developer's
laptop.

The awkward part is that `dim_supplier_contracts` and `fct_contract_compliance` are
ordinary dbt models, and `dbt build` has to work in CI like every other model. A mart that
depended on a live model call would turn every build red.

## Decision

Split the work by whether a model is needed, and let the boundary fall on a file.

**In CI and in the DAG:** generating the contract corpus. It is seeded Python with no model
behind it, deterministic to the byte, and it belongs beside the other generators.

**In neither:** embedding, extraction and retrieval scoring. These are run by hand when the
contracts change, and their output is committed:

- extraction writes `dbt/seeds/contract_terms.csv`, a dbt seed, so the models downstream
  read a version-controlled table rather than calling a model;
- embedding writes `search.contract_chunks` into the local DuckDB file, which is gitignored
  and rebuilt on demand, because only the dashboard reads it.

The seed is the load-bearing part. Extraction is expensive (about twenty minutes on CPU for
twenty-five documents), its input is nearly static, and its output is twenty-five rows of
numbers that a human can read in a diff. Caching it as a reviewed artefact is not a
workaround for CI's limitations, it is what you would want anyway: the numbers a mart is
built on should be inspectable and should change only when somebody meant them to.

Re-running extraction skips documents already present in the seed unless `--force` is
passed, so correcting a formatting mistake costs seconds rather than another full pass.

## Consequences

CI stays fast and hermetic: it regenerates the corpus from the seed value, and because
generation is deterministic the freshly generated catalogue joins cleanly against the
committed terms. That join is the thing this arrangement risks, and it is load-bearing
enough that CI failing on it would be the correct outcome, so it is left to fail loudly
rather than being papered over with an outer join.

The cost is honesty about what is automated. The nightly DAG does not refresh contract
terms, and a new supplier contract does not reach the warehouse until somebody runs
extraction and commits the result. For a corpus that changes a few times a year that is a
reasonable trade; for one that changed daily it would not be, and the fix would be a
worker with a model on it rather than a bigger Airflow container.

Retrieval scoring lives in `scripts/` rather than `tests/` for the same reason. It is a
quality check that needs a model, so it cannot gate a build; what *can* be tested in CI is
the logic around the model, and that is covered — the read-only gate on generated SQL, the
French decimal parsing, supplier resolution, and the fusion constant.
