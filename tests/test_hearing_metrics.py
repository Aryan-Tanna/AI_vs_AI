"""Hearing metrics computed in code after the verdict (D-137)."""

from __future__ import annotations

from typing import Any, Literal

import pytest

from lexarena.evaluator.hearing import bench_metrics, reasoning_alignment, repetition_series, side_metrics
from lexarena.schemas.base import Side
from lexarena.schemas.bench import JudgeDecision, JudgeOpinion
from lexarena.schemas.ground_truth import PrecedentAnalysis, StatutoryAnalysis
from tests.bench_builders import opinion, opinion_pair
from tests.builders import ground_truth, private_turn, published_turn, session
from tests.fakes import WordEmbedder


def decision(*opinions: JudgeOpinion, status: Literal["DECIDED", "ABSTAINED"] = "DECIDED") -> JudgeDecision:
    fields: dict[str, Any] = {"judge": "TEXTUALIST", "opinions": list(opinions), "status": status}
    return JudgeDecision.model_construct(**fields)  # only the fields the metrics read


def test_order_flips_and_first_presented_wins_are_counted() -> None:
    steady = opinion_pair("RESPONDENT", {"I1": "RESPONDENT"})
    flipping = opinion_pair(("PETITIONER", "RESPONDENT"), ({"I1": "PETITIONER"}, {"I1": "RESPONDENT"}))
    m = bench_metrics([decision(*steady.values()), decision(*flipping.values(), status="ABSTAINED")])
    assert (m.judges, m.abstentions, m.opinions) == (2, 1, 4)
    assert m.order_flips == 1 and m.issue_order_flips == 1
    # RESPONDENT_FIRST + RESPONDENT (steady), PETITIONER_FIRST + PETITIONER and RESPONDENT_FIRST + RESPONDENT (flipping)
    assert m.first_presented_wins == 3


def test_reasoning_alignment_matches_sections_and_followed_precedents_only() -> None:
    op = opinion("PETITIONER_FIRST", "RESPONDENT", {"I1": "RESPONDENT"})
    op.issue_decisions[0].governing_rule_ids[:] = ["IBC_2016_SEC_7", "2020_NCLAT_DEL_1#abc", "2019_SC_9#def"]
    truth = ground_truth("C", "<s>").model_copy(
        update={
            "statutory_analysis": [
                StatutoryAnalysis(
                    statute_id="IBC_2016_SEC_7_5", interpretation="<i>", interacts_with=[], source_paras=["P1"]
                ),
                StatutoryAnalysis(
                    statute_id="IBC_2016_SEC_61", interpretation="<i>", interacts_with=[], source_paras=["P1"]
                ),
            ],
            "precedent_analysis": [
                PrecedentAnalysis(
                    name="<a>",
                    precedent_id="2020_NCLAT_DEL_1",
                    forum="NCLAT",
                    bench_strength=None,
                    cited_by="COURT",
                    treatment="FOLLOWED",
                    proposition="<p>",
                    later_history=None,
                    source_paras=["P1"],
                ),
                PrecedentAnalysis(
                    name="<b>",
                    precedent_id="2018_SC_2",
                    forum="SC",
                    bench_strength=None,
                    cited_by="RESPONDENT",
                    treatment="DISTINGUISHED",
                    proposition="<p>",
                    later_history=None,
                    source_paras=["P1"],
                ),
            ],
        }
    )
    r = reasoning_alignment([decision(op)], truth)
    assert r.bench_statutes == ["IBC_2016_SEC_7"] and r.statute_precision == 1.0 and r.statute_recall == 0.5
    assert r.real_precedents == ["2020_NCLAT_DEL_1"]  # a DISTINGUISHED precedent is not governing law
    assert r.precedent_precision == 0.5 and r.precedent_recall == 1.0


def test_an_abstaining_judge_adds_no_governing_law() -> None:
    op = opinion("PETITIONER_FIRST", "RESPONDENT", {"I1": "RESPONDENT"})
    r = reasoning_alignment([decision(op, status="ABSTAINED")], ground_truth("C", "<s>"))
    assert r.bench_statutes == [] and r.bench_precedents == [] and r.statute_precision is None


def test_identical_turns_repeat_fully_and_side_metrics_are_per_side() -> None:
    same = "The same sentence of at least six words."
    assert repetition_series([same, same], WordEmbedder(), 0.92) == [pytest.approx(1.0)]
    assert repetition_series(["only one"], WordEmbedder(), 0.92) == []
    s = session("S", "C")
    order: list[tuple[int, Side]] = [(1, "PETITIONER"), (2, "RESPONDENT"), (3, "PETITIONER")]
    turns = [published_turn("S", "C", t, side).model_copy(update={"published_text": same}) for t, side in order]
    private = [private_turn("S", "C", t, "PETITIONER", "<w>") for t in (1, 3)]
    m = side_metrics("PETITIONER", s, turns, private, ["I1", "I2"], WordEmbedder(), 0.92)
    assert m.turns == 2 and m.issue_coverage == 0.5 and m.first_try_rate == 1.0
    assert m.max_repetition == pytest.approx(1.0) and m.prerequisite_warnings == 2 and m.rebuttal_depth is None
