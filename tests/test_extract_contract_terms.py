"""Tests for the contract-extraction helper.

The model call itself is not tested here: it needs Ollama and its output is scored against
the corpus's answer key by the script's own reporting. What is tested is the coercion
sitting between the model and the warehouse, because that is where a quiet mistake becomes
a wrong number in a mart rather than a visible failure.

The French decimal case is the one that matters. Contracts write "1,3 %", and a naive
float() either raises or, worse, a naive comma-strip turns 1,3 into 13, which is a
tenfold error in a penalty rate that nothing downstream would flag as implausible.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingestion"))

import extract_contract_terms as extractor  # noqa: E402


class TestToNumber:
    @pytest.mark.parametrize("value, expected", [
        (14, 14),
        (1.3, 1.3),
        ("14", 14.0),
        ("1.3", 1.3),
        ("1,3", 1.3),            # French decimal separator
        ("1,3 %", 1.3),          # as it appears in the clause
        (" 2,0 ", 2.0),
        ("60", 60.0),
    ])
    def test_reads_numbers_including_french_decimals(self, value, expected):
        assert extractor._to_number(value) == pytest.approx(expected)

    @pytest.mark.parametrize("value", [
        None, "", "   ", "null", "none", "N/A", "quinze jours", "abc",
    ])
    def test_absent_or_unparseable_becomes_none(self, value):
        assert extractor._to_number(value) is None

    @pytest.mark.parametrize("value", [True, False])
    def test_booleans_are_not_numbers(self, value):
        """json.loads turns `true` into True, which would otherwise cast to 1."""
        assert extractor._to_number(value) is None

    def test_comma_is_a_decimal_point_not_a_thousands_separator(self):
        """The failure worth guarding: stripping the comma would give 13, not 1.3."""
        assert extractor._to_number("1,3") == pytest.approx(1.3)
        assert extractor._to_number("1,3") != 13


class TestFieldContract:
    def test_amendment_fields_are_a_subset_of_all_fields(self):
        assert set(extractor.AMENDMENT_FIELDS) <= set(extractor.FIELDS)

    def test_amendments_cover_exactly_the_restated_clauses(self):
        """An amendment restates the delivery and penalty clauses, and nothing else."""
        assert set(extractor.AMENDMENT_FIELDS) == {
            "lead_time", "penalty_rate", "penalty_cap"
        }

    def test_prompt_asks_for_every_field(self):
        for field in extractor.FIELDS:
            assert field in extractor.PROMPT_TEMPLATE
