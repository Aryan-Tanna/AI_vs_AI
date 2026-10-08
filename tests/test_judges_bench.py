"""From opinions to a verdict (D-048, D-051; SPEC E1): every rule of judges/bench.py."""

from __future__ import annotations

from typing import Any

import pytest

from lexarena.config import load_config
from lexarena.judges.bench import (
    UnsupportedJudgingRuleError,
    decide_bench,
    fold_judge,
    order_swap_gap,
    weighted,
)
from lexarena.schemas.base import Side
from lexarena.schemas.bench import InvalidOpinion, JudgeDecision, JudgeOpinion, Persona, PresentationOrder, Upholds
from tests.bench_builders import SHA, draft, opinion, opinion_pair, scores
from tests.conftest import CONFIG_V1

CFG = load_config(CONFIG_V1).judging
ISSUES = ["I1", "I2"]


def fold(persona: Persona, opinions: Any, cfg: Any = CFG) -> JudgeDecision:
    return fold_judge(
        persona, opinions, ISSUES, cfg, persona_prompt="<prompt>", persona_sha256=SHA, persona_approved=True
    )


def judge(
    persona: Persona,
    result: Side | tuple[Side, Side],
    upholds: dict[str, Upholds] | None = None,
    **kwargs: Any,
) -> JudgeDecision:
    held: dict[str, Upholds] = upholds or {"I1": "PETITIONER", "I2": "PETITIONER"}
    return fold(persona, opinion_pair(result, held, **kwargs))


def invalid_pair() -> dict[PresentationOrder, JudgeOpinion | InvalidOpinion]:
    pair: dict[PresentationOrder, JudgeOpinion | InvalidOpinion] = {
        **opinion_pair("PETITIONER", {"I1": "PETITIONER", "I2": "PETITIONER"})
    }
    pair["RESPONDENT_FIRST"] = InvalidOpinion(
        order="RESPONDENT_FIRST", revised=True, problems=["UNKNOWN_RULE_ID I1: X"], draft=draft("PETITIONER", [])
    )
    return pair


# ---------------------------------------------------------------- one persona


def test_weighted_score_uses_config_weights() -> None:
    w = CFG.weights
    s = scores(1.0).model_copy(update={"accuracy": 0.0})
    assert weighted(s, w) == pytest.approx(w.consistency + w.rebuttal + w.grounding)


def test_persona_decides_when_both_orders_agree() -> None:
    d = judge("TEXTUALIST", "PETITIONER")
    assert (d.status, d.result, d.abstain_reason) == ("DECIDED", "PETITIONER", None)
    assert [r.upholds for r in d.issue_results] == ["PETITIONER", "PETITIONER"]


def test_persona_abstains_when_the_orders_disagree_on_the_result() -> None:
    d = judge("TEXTUALIST", ("PETITIONER", "RESPONDENT"))
    assert (d.status, d.result, d.abstain_reason) == ("ABSTAINED", None, "ORDER_SWAP_DISAGREEMENT")


def test_persona_abstains_on_an_issue_its_orders_decided_differently() -> None:
    d = judge(
        "TEXTUALIST",
        "PETITIONER",
        ({"I1": "PETITIONER", "I2": "RESPONDENT"}, {"I1": "PETITIONER", "I2": "NEITHER"}),  # type: ignore[arg-type]
    )
    assert d.status == "DECIDED"
    assert [(r.issue_id, r.status, r.upholds) for r in d.issue_results] == [
        ("I1", "DECIDED", "PETITIONER"),
        ("I2", "ABSTAINED", None),
    ]


def test_an_invalid_opinion_makes_the_persona_abstain_on_everything() -> None:
    d = fold("TEXTUALIST", invalid_pair())
    assert (d.status, d.abstain_reason) == ("ABSTAINED", "INVALID_OPINION")
    assert all(r.status == "ABSTAINED" for r in d.issue_results)
    assert d.order_swap_gap is None and d.advocacy is not None  # the valid opinion still scored


def test_order_swap_gap_is_the_largest_issue_side_difference() -> None:
    a = opinion("PETITIONER_FIRST", "PETITIONER", {"I1": "PETITIONER"}, p_score=0.9, r_score=0.4)
    b = opinion("RESPONDENT_FIRST", "PETITIONER", {"I1": "PETITIONER"}, p_score=0.6, r_score=0.4)
    assert order_swap_gap(a, b, CFG.weights) == pytest.approx(0.3)


def test_undefined_rule_is_refused_not_resolved() -> None:
    cfg = CFG.model_copy(update={"abstain_on_order_swap_disagreement": False})
    with pytest.raises(UnsupportedJudgingRuleError):
        fold("TEXTUALIST", opinion_pair("PETITIONER", {"I1": "PETITIONER"}), cfg)
    with pytest.raises(UnsupportedJudgingRuleError):
        decide_bench([judge("TEXTUALIST", "PETITIONER")], ISSUES, cfg)


# ---------------------------------------------------------------- the bench


def test_unanimous_bench() -> None:
    ds = [
        judge(p, "RESPONDENT", {"I1": "RESPONDENT", "I2": "NEITHER"})
        for p in ("TEXTUALIST", "PURPOSIVIST", "PROCEDURALIST")
    ]
    v = decide_bench(ds, ISSUES, CFG)
    assert (v.status, v.winner, v.decided_by, v.dissenting_judges) == ("DECIDED", "RESPONDENT", "MAJORITY", [])
    assert [(f.issue_id, f.upholds) for f in v.issue_findings] == [("I1", "RESPONDENT"), ("I2", "NEITHER")]


def test_two_to_one_majority_records_the_dissent() -> None:
    ds = [judge("TEXTUALIST", "PETITIONER"), judge("PURPOSIVIST", "PETITIONER"), judge("PROCEDURALIST", "RESPONDENT")]
    v = decide_bench(ds, ISSUES, CFG)
    assert (v.winner, v.decided_by, v.dissenting_judges) == ("PETITIONER", "MAJORITY", ["PROCEDURALIST"])
    assert v.votes == {"PETITIONER": 2, "RESPONDENT": 1}


def test_even_split_goes_to_the_advocacy_score() -> None:
    ds = [
        judge("TEXTUALIST", "PETITIONER", p_score=0.9, r_score=0.2),
        judge("PURPOSIVIST", "RESPONDENT", p_score=0.9, r_score=0.2),
        judge("PROCEDURALIST", ("PETITIONER", "RESPONDENT"), p_score=0.9, r_score=0.2),
    ]
    v = decide_bench(ds, ISSUES, CFG)
    assert (v.winner, v.decided_by, v.abstaining_judges) == ("PETITIONER", "TIE_BREAK", ["PROCEDURALIST"])
    assert v.dissenting_judges == ["PURPOSIVIST"]


def test_even_split_within_the_margin_goes_to_accuracy() -> None:
    w = CFG.weights
    # Equal weighted scores (the respondent's accuracy lead is offset in consistency), so the accuracy component,
    # which favours the respondent by more than the margin, decides (SPEC E1).
    lead = CFG.tie_margin * 5  # literal-ok: test arithmetic
    p = scores(0.5).model_copy(update={"accuracy": 0.5 - lead, "consistency": 0.5 + lead * w.accuracy / w.consistency})
    r = scores(0.5)
    ds = [judge("TEXTUALIST", "PETITIONER", p_dims=p, r_dims=r), judge("PURPOSIVIST", "RESPONDENT", p_dims=p, r_dims=r)]
    v = decide_bench(ds, ISSUES, CFG)
    assert v.advocacy is not None
    assert v.advocacy["PETITIONER"] == pytest.approx(v.advocacy["RESPONDENT"])
    assert (v.winner, v.decided_by) == ("RESPONDENT", "TIE_BREAK")


def test_even_split_with_no_score_difference_is_unstable() -> None:
    ds = [judge("TEXTUALIST", "PETITIONER"), judge("PURPOSIVIST", "RESPONDENT")]
    v = decide_bench(ds, ISSUES, CFG)
    assert (v.status, v.unstable_reason, v.winner) == ("UNSTABLE", "UNBROKEN_TIE", None)


def test_too_few_deciding_judges_is_unstable_whatever_the_score() -> None:
    """Planted-bug guard for D-051: a lopsided score must not decide a case one judge decided."""
    ds = [
        judge("TEXTUALIST", "PETITIONER", p_score=1.0, r_score=0.0),
        judge("PURPOSIVIST", ("PETITIONER", "RESPONDENT"), p_score=1.0, r_score=0.0),
        fold("PROCEDURALIST", invalid_pair()),
    ]
    v = decide_bench(ds, ISSUES, CFG)
    assert (v.status, v.unstable_reason) == ("UNSTABLE", "TOO_FEW_DECIDING_JUDGES")
    assert v.advocacy is not None and v.advocacy["PETITIONER"] > v.advocacy["RESPONDENT"]


def test_min_deciding_judges_comes_from_config() -> None:
    ds = [judge("TEXTUALIST", "PETITIONER"), judge("PURPOSIVIST", "PETITIONER")]
    assert decide_bench(ds, ISSUES, CFG).status == "DECIDED"
    stricter = CFG.model_copy(update={"min_deciding_judges": 3})
    assert decide_bench(ds, ISSUES, stricter).unstable_reason == "TOO_FEW_DECIDING_JUDGES"


def test_issue_without_a_strict_majority_is_unstable() -> None:
    ds = [
        judge("TEXTUALIST", "PETITIONER", {"I1": "PETITIONER", "I2": "PETITIONER"}),
        judge("PURPOSIVIST", "PETITIONER", {"I1": "RESPONDENT", "I2": "PETITIONER"}),
        judge("PROCEDURALIST", "PETITIONER", {"I1": "NEITHER", "I2": "RESPONDENT"}),
    ]
    v = decide_bench(ds, ISSUES, CFG)
    i1, i2 = v.issue_findings
    assert (i1.status, i1.upholds, i1.votes) == ("UNSTABLE", None, {"PETITIONER": 1, "RESPONDENT": 1, "NEITHER": 1})
    assert (i2.status, i2.upholds, i2.dissenting_judges) == ("DECIDED", "PETITIONER", ["PROCEDURALIST"])


def test_issue_decided_by_too_few_judges_is_unstable() -> None:
    ds = [
        judge("TEXTUALIST", "PETITIONER"),
        fold("PURPOSIVIST", invalid_pair()),
        fold("PROCEDURALIST", invalid_pair()),
    ]
    v = decide_bench(ds, ISSUES, CFG)
    assert all(f.status == "UNSTABLE" for f in v.issue_findings)
