"""D-145: the evaluator scans a session's model texts for the real party names after the verdict (D-143 automated)."""

from __future__ import annotations

from lexarena.evaluator.evaluate import recalled_names, scanned_names

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


def test_a_name_the_session_showed_the_models_is_not_a_recall() -> None:
    """DEV_0013: a party that is a large bank also appeared in precedent titles the lawyers were served; naming what
    one was shown is not memory (D-147)."""
    names = ["Northern Cooperative Bank", "Ravindra Kolhatkar"]
    texts = ["- Northern Cooperative Bank v. Some Liquidator (2018)", "Ravindra Kolhatkar maybe"]
    shown = ["[2025_NCLAT_DEL_1#x] Northern Cooperative Bank vs. Another & Anr."]
    assert recalled_names(texts, names, GENERIC, shown_texts=shown) == ["Ravindra Kolhatkar"]


def test_institutional_parties_are_not_scanned() -> None:
    """DEV_0014: a lawyer listed famous unrelated precedents from memory, naming a bank and the regulator that were
    also parties here; an institution named alone is not recall of this case (D-148)."""
    amap = {
        "Bank-A": "Northern Cooperative Bank",
        "Authority-B": "Board of Regulators",
        "Person-C": "Ravindra Kolhatkar",
    }
    assert scanned_names(amap, ["Bank", "Authority"]) == ["Ravindra Kolhatkar"]
    assert scanned_names(amap, []) == list(amap.values())
