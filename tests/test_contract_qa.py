"""Tests for contract retrieval.

Retrieval quality itself is measured, not asserted: scripts/evaluate_retrieval.py scores
it against a golden set, because "did it find the right clause" is a number that moves,
not a boolean. What is pinned here is the logic around it that has one correct answer,
and that runs without Ollama so CI can cover it.

Supplier resolution earns tests because it is what turns the entity in a question into a
`where` clause, and getting it wrong silently searches the wrong supplier's contracts and
answers confidently from them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboards"))

import contract_qa  # noqa: E402


@pytest.fixture
def suppliers():
    return pd.DataFrame([
        {"supplier_id": "SUP-0001", "supplier_name": "Laurent et Fils"},
        {"supplier_id": "SUP-0003", "supplier_name": "Martinez SA"},
        {"supplier_id": "SUP-0009", "supplier_name": "Regnier"},
        {"supplier_id": "SUP-0020", "supplier_name": "Regnier Frères"},
    ])


class TestResolveSupplier:
    @pytest.mark.parametrize("question, expected", [
        ("Quel est le délai de livraison de Martinez SA ?", "SUP-0003"),
        ("Quelle pénalité pour Laurent et Fils ?", "SUP-0001"),
        ("martinez sa livre en combien de jours ?", "SUP-0003"),      # case insensitive
        ("Et pour MARTINEZ SA ?", "SUP-0003"),
    ])
    def test_finds_the_named_supplier(self, question, expected, suppliers):
        assert contract_qa.resolve_supplier(question, suppliers) == expected

    def test_longest_name_wins(self, suppliers):
        """"Regnier" is a substring of "Regnier Frères"; the more specific one is meant."""
        question = "Quel préavis pour Regnier Frères ?"
        assert contract_qa.resolve_supplier(question, suppliers) == "SUP-0020"

    def test_shorter_name_still_matches_on_its_own(self, suppliers):
        assert contract_qa.resolve_supplier("Et Regnier ?", suppliers) == "SUP-0009"

    @pytest.mark.parametrize("question", [
        "Quel est le délai de livraison habituel ?",
        "Quelles sont les pénalités de retard ?",
        "",
    ])
    def test_no_supplier_named_means_no_filter(self, question, suppliers):
        """None must mean "search everything", never "search supplier None"."""
        assert contract_qa.resolve_supplier(question, suppliers) is None


class TestContext:
    def test_context_labels_each_clause_with_its_document(self):
        """The model is told to cite, so every clause has to arrive carrying its id."""
        clauses = pd.DataFrame([
            {"document_id": "CTR-2026-0009-A1", "article_title": "Modification du délai",
             "chunk_text": "sept jours ouvrés"},
            {"document_id": "CTR-2026-0009", "article_title": "Conditions de paiement",
             "chunk_text": "quarante-cinq jours"},
        ])
        context = contract_qa._context(clauses)
        assert "[CTR-2026-0009-A1]" in context
        assert "[CTR-2026-0009]" in context
        assert "sept jours ouvrés" in context


class TestFusionConstant:
    def test_rrf_k_is_scaled_to_the_candidate_pool(self):
        """The literature's 60 flattens ranks 1-3 when a pool is ten clauses.

        Guarding the value because raising it back to a "standard" number silently costs
        accuracy on exactly the questions that matter: measured on the golden set, k=60
        left the correct clause losing a tie decided by floating-point noise.
        """
        assert contract_qa.RRF_K <= 10
