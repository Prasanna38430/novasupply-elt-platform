"""Tests for the NL-to-SQL helper.

The model itself is not tested here, its output is not deterministic enough to assert on
and it needs a running Ollama. What is tested is everything around it: the read-only gate
that decides whether generated SQL is allowed to reach the warehouse at all, the row cap,
and the repair loop's control flow. Those are the parts where a bug is dangerous rather
than merely wrong, and they run without Ollama, so CI covers them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboards"))

import nl_query  # noqa: E402


class TestIsSafeSelect:
    @pytest.mark.parametrize("sql", [
        "select 1",
        "SELECT * FROM {marts}.fct_sales",
        "  select a from t  ",
        "with x as (select 1) select * from x",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "select count(*) from t where name = 'offset'",   # 'set' inside a word is fine
        "select dropped_count, load_date, use_rate from t",  # keywords as substrings
        "select a from t limit 10;",                      # single trailing semicolon
    ])
    def test_allows_read_only_queries(self, sql):
        assert nl_query.is_safe_select(sql) is True

    @pytest.mark.parametrize("sql", [
        "insert into t values (1)",
        "INSERT INTO t VALUES (1)",
        "update t set x = 1",
        "delete from t",
        "drop table t",
        "alter table t add column c int",
        "truncate table t",
        "create table t as select 1",
        "grant select on t to public",
        "merge into t using s on true",
        "copy t to 'out.csv'",
        "attach 'other.db'",
        "install httpfs",
        "pragma database_list",
        "explain select 1",          # not a SELECT/WITH start
        "",
        "   ",
        "-- select 1",               # comment, not a statement
    ])
    def test_rejects_writes_and_non_selects(self, sql):
        assert nl_query.is_safe_select(sql) is False

    @pytest.mark.parametrize("sql", [
        "select 1; drop table t",
        "select 1; delete from t;",
        "select 1 ; insert into t values (1)",
    ])
    def test_rejects_piggybacked_second_statement(self, sql):
        """A write must not ride along behind a legitimate-looking SELECT."""
        assert nl_query.is_safe_select(sql) is False


class TestCapRows:
    def test_appends_limit_when_absent(self):
        assert nl_query.cap_rows("select * from t", 100).endswith("limit 100")

    @pytest.mark.parametrize("sql", [
        "select * from t limit 5",
        "select * from t LIMIT 5",
        "select * from t limit 5   ",
    ])
    def test_respects_an_existing_limit(self, sql):
        assert nl_query.cap_rows(sql, 100) == sql

    def test_inner_limit_does_not_count_as_capped(self):
        """A LIMIT inside a subquery does not bound the result set, so still cap it."""
        sql = "select * from (select x from t limit 5) a"
        assert nl_query.cap_rows(sql, 100).endswith("limit 100")


class TestAnswerRepairLoop:
    """The repair loop is control flow worth pinning down: it must retry exactly once."""

    def test_returns_first_attempt_when_it_runs(self, monkeypatch):
        monkeypatch.setattr(nl_query, "generate_sql", lambda q, on_token=None: "select 1")
        monkeypatch.setattr(nl_query, "repair_sql", lambda *a, **k: pytest.fail("should not repair"))

        sql, rows, repaired = nl_query.answer("q", runner=lambda s: [("ok",)])

        assert repaired is False
        assert rows == [("ok",)]
        assert sql.startswith("select 1")

    def test_repairs_once_after_a_database_error(self, monkeypatch):
        monkeypatch.setattr(nl_query, "generate_sql", lambda q, on_token=None: "select bad")
        monkeypatch.setattr(nl_query, "repair_sql", lambda *a, **k: "select good")

        calls = []

        def runner(sql):
            calls.append(sql)
            if "bad" in sql:
                raise RuntimeError("Binder Error: no column 'bad'")
            return [("fixed",)]

        sql, rows, repaired = nl_query.answer("q", runner=runner)

        assert repaired is True
        assert rows == [("fixed",)]
        assert "good" in sql
        assert len(calls) == 2

    def test_gives_up_after_the_second_failure(self, monkeypatch):
        monkeypatch.setattr(nl_query, "generate_sql", lambda q, on_token=None: "select bad")
        monkeypatch.setattr(nl_query, "repair_sql", lambda *a, **k: "select alsobad")

        def runner(sql):
            raise RuntimeError(f"boom: {sql.splitlines()[0]}")

        with pytest.raises(RuntimeError) as caught:
            nl_query.answer("q", runner=runner)

        # Both errors are reported, so the failure is diagnosable from the message alone.
        assert "select bad" in str(caught.value)
        assert "select alsobad" in str(caught.value)

    def test_unsafe_sql_never_reaches_the_runner(self, monkeypatch):
        monkeypatch.setattr(nl_query, "_complete", lambda prompt, on_token=None: "drop table t")

        with pytest.raises(nl_query.UnsafeGeneratedSQL):
            nl_query.answer("q", runner=lambda s: pytest.fail("runner must not be called"))


class TestPromptGrounding:
    """Cheap guards against the prompt drifting away from the real warehouse."""

    def test_prompt_builds_and_carries_the_question(self):
        prompt = nl_query.PROMPT_TEMPLATE.format(
            schema=nl_query.SCHEMA_DDL,
            glossary=nl_query.GLOSSARY,
            few_shot=nl_query.FEW_SHOT,
            question="how many stores?",
        )
        assert "how many stores?" in prompt
        # The {marts} placeholder must survive formatting; app.py swaps it per warehouse.
        assert "{marts}.fct_sales" in prompt

    @pytest.mark.parametrize("table", [
        "dim_suppliers", "dim_products", "dim_stores", "dim_date",
        "fct_sales", "fct_inventory", "fct_purchase_orders",
    ])
    def test_every_mart_is_described(self, table):
        assert table in nl_query.SCHEMA_DDL

    def test_grain_traps_are_stated(self):
        """These two are the difference between a plausible number and a correct one."""
        assert "max(snapshot_date)" in nl_query.GLOSSARY
        assert "is_open = false" in nl_query.GLOSSARY
