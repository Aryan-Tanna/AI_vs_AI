"""Evaluator: alignment rules, statistics and the report (BUILD_PLAN Step 12; SPEC G1, G2, I2; D-072). Offline."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from lexarena.evaluator.align import evaluate
from lexarena.evaluator.report import evaluation_report
from lexarena.evaluator.stats import balanced_accuracy, bootstrap_ci, macro_f1, mcnemar_exact
from lexarena.judges.bench import decide_bench, fold_judge
from lexarena.schemas.bench import BenchVerdict, JudgeDecision
from lexarena.schemas.evaluation import BaselinePrediction, CaseOutcome
from lexarena.schemas.ground_truth import CaseGroundTruth
from lexarena.schemas.session import IssueAlignment
from tests import builders
from tests.bench_builders import SHA, opinion_pair
from tests.test_judges_bench import CFG as JUDGING
from tests.test_judges_personas import CFG

ISSUES = ["I1", "I2", "I3"]


def truth(overall: str, findings: dict[str, tuple[str, str]]) -> CaseGroundTruth:
    doc = builders.ground_truth("TESTCASE_0001", "<sentinel>").to_document()
    template = doc["issue_findings"][0]
    doc["issue_findings"] = [{**template, "issue_id": i, "favours": f, "driver": d} for i, (f, d) in findings.items()]
    doc["conclusion"]["overall_favours"] = overall
    return CaseGroundTruth.model_validate(doc)


def three_issue_judge(persona: Any, result: Any, held: dict[str, Any]) -> JudgeDecision:
    return fold_judge(
        persona,
        opinion_pair(result, held),
        ISSUES,
        JUDGING,
        persona_prompt="<p>",
        persona_sha256=SHA,
        persona_approved=True,
    )


def bench(result: Any = "PETITIONER", upholds: dict[str, Any] | None = None) -> BenchVerdict:
    held = upholds or {"I1": "PETITIONER", "I2": "PETITIONER", "I3": "RESPONDENT"}
    ds = [three_issue_judge(p, result, held) for p in ("TEXTUALIST", "PURPOSIVIST", "PROCEDURALIST")]
    return decide_bench(ds, ISSUES, JUDGING)


# ---------------------------------------------------------------- alignment


def test_alignment_compares_issue_by_issue_and_skips_evidence_driven_ones() -> None:
    gt = truth(
        "PETITIONER", {"I1": ("PETITIONER", "LAW"), "I2": ("RESPONDENT", "MIXED"), "I3": ("PETITIONER", "EVIDENCE")}
    )
    e = evaluate(bench(), gt, ISSUES)
    assert [(i.issue_id, i.bench, i.real, i.aligned) for i in e.issues] == [
        ("I1", "PETITIONER", "PETITIONER", True),
        ("I2", "PETITIONER", "RESPONDENT", False),
        ("I3", "RESPONDENT", "PETITIONER", False),
    ]
    assert e.issue_alignment == 0.5  # I3 is evidence-driven: stored, not counted
    assert e.winner_matches_real is True and e.real_overall == "PETITIONER"


def test_mixed_real_outcome_has_no_verdict_alignment() -> None:
    e = evaluate(bench(), truth("MIXED", {"I1": ("PETITIONER", "LAW")}), ISSUES)
    assert e.winner_matches_real is None and e.issue_alignment == 1.0


def test_unstable_bench_has_no_verdict_alignment_and_unstable_issues_are_not_compared() -> None:
    held = {"I1": "PETITIONER", "I2": "PETITIONER", "I3": "RESPONDENT"}
    ds = [
        three_issue_judge("TEXTUALIST", "PETITIONER", held),
        three_issue_judge("PURPOSIVIST", "RESPONDENT", {**held, "I3": "PETITIONER"}),
    ]
    unstable = decide_bench(ds, ISSUES, JUDGING)
    assert unstable.status == "UNSTABLE"
    e = evaluate(unstable, truth("PETITIONER", {"I3": ("RESPONDENT", "LAW")}), ISSUES)
    assert e.winner_matches_real is None
    assert [(i.issue_id, i.bench, i.aligned) for i in e.issues] == [("I3", None, None)]
    assert e.issue_alignment is None


def test_a_framed_issue_the_court_did_not_decide_is_skipped() -> None:
    e = evaluate(bench(), truth("RESPONDENT", {"I2": ("PETITIONER", "LAW")}), ISSUES)
    assert [i.issue_id for i in e.issues] == ["I2"] and e.winner_matches_real is False


# ---------------------------------------------------------------- statistics


def test_balanced_accuracy_does_not_reward_always_saying_the_majority() -> None:
    truth_ = ["P"] * 8 + ["R"] * 2
    assert balanced_accuracy(truth_, ["P"] * 10) == 0.5
    assert balanced_accuracy(truth_, truth_) == 1.0


def test_macro_f1_known_value() -> None:
    # P: tp=1 fp=1 fn=1 -> 0.5 ; R: tp=1 fp=1 fn=1 -> 0.5
    assert macro_f1(["P", "P", "R", "R"], ["P", "R", "P", "R"], ["P", "R"]) == pytest.approx(0.5)
    assert macro_f1([], [], ["P"]) is None


@pytest.mark.parametrize(
    ("b", "c", "expected"),
    [(0, 0, 1.0), (0, 6, 2 / 64), (3, 3, 1.0), (1, 9, 22 / 1024)],
)
def test_mcnemar_exact_known_values(b: int, c: int, expected: float) -> None:
    assert mcnemar_exact(b, c) == pytest.approx(expected)


def test_bootstrap_is_reproducible_and_seeded() -> None:
    items = [x / 7 for x in range(20)]  # literal-ok: varied values, so intervals depend on the seed

    def mean(xs: Sequence[float]) -> float:
        return float(sum(xs)) / len(xs)

    a = bootstrap_ci(items, mean, resamples=500, level=0.9, seed=7)
    assert a == bootstrap_ci(items, mean, resamples=500, level=0.9, seed=7)
    assert a != bootstrap_ci(items, mean, resamples=500, level=0.9, seed=8)
    assert a is not None and a[0] <= mean(items) <= a[1]
    assert bootstrap_ci([], mean, resamples=10, level=0.9, seed=7) is None


# ---------------------------------------------------------------- report


def outcome(n: int, winner: Any, real: Any, *, single: Any = None, **change: Any) -> CaseOutcome:
    base: dict[str, Any] = {
        "case_id": f"TESTCASE_{n:04d}",
        "session_id": f"S{n}",
        "split": "DEV",
        "evidence_dependency": "LAW_ONLY",
        "memorization_probe": "NOT_IDENTIFIED",
        "bench_status": "DECIDED" if winner else "UNSTABLE",
        "bench_winner": winner,
        "real_overall": real,
        "issues": [
            IssueAlignment(
                issue_id="I1",
                bench=winner,
                real=real if real != "MIXED" else "NEITHER",
                driver="LAW",
                aligned=None if winner is None else winner == real,
            )
        ],
        "single_llm": None
        if single is None
        else BaselinePrediction(
            case_id=f"TESTCASE_{n:04d}",
            kind="SINGLE_LLM",
            model="<model>",
            prompt_id="<prompt>",
            prompt_sha256=SHA,
            overall=single,
            issues={"I1": single},
            problems=[],
        ),
    }
    return CaseOutcome.model_validate({**base, **change})


def scores(report: Any, subset: str, level: str = "verdict") -> dict[str, Any]:
    sub = next(s for s in report.subsets if s.subset == subset)
    return {s.system: s for s in getattr(sub, level).scores}


def test_majority_class_uses_only_earlier_cases() -> None:
    outcomes = [
        outcome(1, "PETITIONER", "RESPONDENT"),
        outcome(2, "PETITIONER", "RESPONDENT"),
        outcome(3, "PETITIONER", "PETITIONER"),
    ]
    report = evaluation_report(outcomes, CFG.evaluation, CFG.seed)
    maj = scores(report, "ALL")["MAJORITY_CLASS"]
    # case 1: no history (no prediction); case 2: R (right); case 3: R (wrong)
    assert (maj.eligible, maj.predicted, maj.accuracy) == (3, 2, 0.5)


def test_unstable_lowers_coverage_not_accuracy_and_mcnemar_pairs() -> None:
    outcomes = [
        outcome(1, "PETITIONER", "PETITIONER", single="RESPONDENT"),
        outcome(2, None, "RESPONDENT", single="RESPONDENT"),
        outcome(3, "RESPONDENT", "RESPONDENT", single="PETITIONER"),
        outcome(4, "PETITIONER", "MIXED", single="PETITIONER"),
    ]
    report = evaluation_report(outcomes, CFG.evaluation, CFG.seed)
    s = scores(report, "ALL")
    assert (s["BENCH"].eligible, s["BENCH"].predicted, s["BENCH"].accuracy) == (3, 2, 1.0)
    assert s["SINGLE_LLM"].accuracy == pytest.approx(1 / 3)
    all_ = next(x for x in report.subsets if x.subset == "ALL")
    cmp = all_.verdict.bench_vs_single_llm
    assert (cmp.pairs, cmp.only_a_right, cmp.only_b_right) == (2, 2, 0)
    assert (all_.unstable_verdicts, all_.mixed_outcomes) == (1, 1)


def test_headline_excludes_memorised_and_evidence_decided_cases() -> None:
    outcomes = [
        outcome(1, "PETITIONER", "PETITIONER"),
        outcome(2, "PETITIONER", "RESPONDENT", memorization_probe="IDENTIFIED"),
        outcome(3, "PETITIONER", "RESPONDENT", evidence_dependency="EVIDENCE_DECIDED"),
    ]
    report = evaluation_report(outcomes, CFG.evaluation, CFG.seed)
    cases = {s.subset: s.cases for s in report.subsets}
    assert cases == {"HEADLINE": 1, "ALL": 3, "MEMORISED": 1, "EVIDENCE_DECIDED": 1, "SPLIT_DEV": 3}
    assert scores(report, "HEADLINE")["BENCH"].accuracy == 1.0
