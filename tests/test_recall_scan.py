"""D-145: the evaluator scans a session's model texts for the real party names after the verdict (D-143 automated)."""

from __future__ import annotations

from lexarena.evaluator.evaluate import recalled_names

NAMES = ["Mansi Brar Fernandes", "Tata Capital Housing Finance Limited"]
GENERIC = ["limited", "finance", "housing"]


def test_a_full_name_in_the_reasoning_is_a_recall() -> None:
    """DEV_0010: a judge wrote the real appellant's full name while trying to place the case."""
    assert recalled_names(
        ["The Supreme Court in 'Mansi Brar Fernandes v. R.B. Enterprises' maybe"], NAMES, GENERIC
    ) == ["Mansi Brar Fernandes"]


def test_one_ordinary_word_of_a_name_is_not() -> None:
    assert recalled_names(["the capital structure of the debtor", "Capital is risk money"], NAMES, GENERIC) == []


def test_two_distinct_words_of_one_name_as_written_are() -> None:
    assert recalled_names(["Tata ... the Capital account"], NAMES, GENERIC) == ["Tata Capital Housing Finance Limited"]
    assert recalled_names(["tata ... capital"], NAMES, GENERIC) == []  # not written as the name is
