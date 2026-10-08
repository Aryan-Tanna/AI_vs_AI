"""Bench diagnostics against limits fixed in config before measuring (BUILD_PLAN Step 11; SPEC E1; D-024)."""

from __future__ import annotations

from lexarena.judges.bench import decide_bench
from lexarena.judges.report import bench_report
from lexarena.schemas.bench import JudgeDecision
from tests.test_judges_bench import CFG, ISSUES, fold, invalid_pair, judge


def session(decisions: list[JudgeDecision]) -> tuple[list[JudgeDecision], object]:
    return decisions, decide_bench(decisions, ISSUES, CFG)


def test_report_counts_disagreement_gaps_abstentions_and_wins() -> None:
    sessions = [
        session(
            [
                judge("TEXTUALIST", "PETITIONER"),
                judge("PURPOSIVIST", "PETITIONER"),
                judge("PROCEDURALIST", "PETITIONER"),
            ]
        ),
        session(
            [
                judge("TEXTUALIST", ("PETITIONER", "RESPONDENT")),
                judge("PURPOSIVIST", "RESPONDENT"),
                fold("PROCEDURALIST", invalid_pair()),
            ]
        ),
    ]
    report = bench_report(sessions, CFG)  # type: ignore[arg-type]
    t, p, pr = report.personas
    assert report.sessions == 2 and report.verdicts == {"PETITIONER": 1, "UNSTABLE_TOO_FEW_DECIDING_JUDGES": 1}
    assert (t.cases, t.decided, t.order_swap_disagreement_rate) == (2, 1, 0.5)
    assert t.disagreement_over_limit == (CFG.max_order_swap_disagreement_rate < 0.5)
    assert t.abstained == {"ORDER_SWAP_DISAGREEMENT": 1}
    assert p.wins == {"PETITIONER": 1, "RESPONDENT": 1}
    assert (pr.invalid_opinions, pr.abstained) == (1, {"INVALID_OPINION": 1})
    assert pr.order_swap_disagreement_rate == 0.0  # only the case where both opinions were valid counts
    assert t.gap.count == 2 and t.gap.over_limit == 0
    assert report.limits["order_swap_max_gap"] == CFG.order_swap_max_gap


def test_role_bias_is_flagged_only_after_enough_cases() -> None:
    few = [session([judge("TEXTUALIST", "PETITIONER")]) for _ in range(3)]
    assert bench_report(few, CFG).personas[0].role_bias_flag is None  # type: ignore[arg-type]
    cfg = CFG.model_copy(update={"persona_role_min_cases": 3})
    assert bench_report(few, cfg).personas[0].role_bias_flag == "PETITIONER"  # type: ignore[arg-type]
