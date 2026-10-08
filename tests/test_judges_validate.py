"""The judge validator (ARCHITECTURE §5; SPEC I3-6): every reason cites only what exists and was shown."""

from __future__ import annotations

from typing import Any

from lexarena.judges.validate import Allowed, check_opinion, finalize
from lexarena.schemas.bench import InvalidOpinion, JudgeOpinion
from tests.bench_builders import draft

ALLOWED = Allowed(
    issue_ids=["I1", "I2"],
    statute_ids={"<statute A>"},
    precedent_uids={"<precedent uid>"},
    record_ids={"F1", "C1", "EX-1", "AM1"},
)


def decision(issue: str, upholds: str = "PETITIONER", **change: Any) -> dict[str, Any]:
    return {
        "issue_id": issue,
        "governing_rule_ids": ["<statute A>"],
        "record_ids": ["F1"],
        "upholds": upholds,
        **change,
    }


def test_a_clean_opinion_has_no_problems() -> None:
    d = draft("PETITIONER", [decision("I1"), decision("I2", governing_rule_ids=["<precedent uid>"], record_ids=[])])
    assert check_opinion(d, ALLOWED) == []
    assert isinstance(finalize(d, "PETITIONER_FIRST", revised=False, problems=[]), JudgeOpinion)


def test_missing_unknown_and_duplicate_issues() -> None:
    d = draft("PETITIONER", [decision("I1"), decision("I1"), decision("I7")])
    problems = check_opinion(d, ALLOWED)
    assert "MISSING_ISSUE I2: decide this issue" in problems
    assert "UNKNOWN_ISSUE I7: not a framed issue" in problems
    assert "DUPLICATE_ISSUE I1: decide each issue once" in problems


def test_ids_not_shown_to_the_judge_are_problems() -> None:
    d = draft(
        "PETITIONER",
        [
            decision("I1", governing_rule_ids=["<statute never shown>", "F1"]),
            decision("I2", record_ids=["F99"]),
        ],
    )
    problems = check_opinion(d, ALLOWED)
    assert any(p.startswith("UNKNOWN_RULE_ID I1: <statute never shown>") for p in problems)
    assert any(p.startswith("UNKNOWN_RULE_ID I1: F1") for p in problems)  # a record item is not a rule
    assert any(p.startswith("UNKNOWN_RECORD_ID I2: F99") for p in problems)


def test_a_decision_needs_a_governing_rule() -> None:
    d = draft("PETITIONER", [decision("I1", governing_rule_ids=[]), decision("I2")])
    assert any(p.startswith("NO_GOVERNING_RULE I1") for p in check_opinion(d, ALLOWED))


def test_advocacy_must_cover_exactly_the_decided_issues() -> None:
    d = draft("PETITIONER", [decision("I1"), decision("I2")], advocacy_issues=["I1"])
    assert any(p.startswith("ADVOCACY_MISMATCH") for p in check_opinion(d, ALLOWED))


def test_overall_result_must_follow_from_one_sided_findings() -> None:
    d = draft("RESPONDENT", [decision("I1", "PETITIONER"), decision("I2", "NEITHER")])
    assert any(p.startswith("RESULT_CONTRADICTS_FINDINGS") for p in check_opinion(d, ALLOWED))


def test_mixed_findings_leave_the_result_to_the_judge() -> None:
    d = draft("RESPONDENT", [decision("I1", "PETITIONER"), decision("I2", "RESPONDENT")])
    assert check_opinion(d, ALLOWED) == []


def test_remaining_problems_make_an_invalid_opinion_that_keeps_the_draft() -> None:
    d = draft("PETITIONER", [decision("I1")])
    out = finalize(d, "RESPONDENT_FIRST", revised=True, problems=["MISSING_ISSUE I2: decide this issue"])
    assert isinstance(out, InvalidOpinion)
    assert out.draft == d and out.revised and out.order == "RESPONDENT_FIRST"


def test_a_malformed_draft_becomes_invalid_not_an_exception() -> None:
    d = draft("PETITIONER", [decision("not-an-issue-id")])
    out = finalize(d, "PETITIONER_FIRST", revised=False, problems=[])
    assert isinstance(out, InvalidOpinion)
    assert out.problems[0].startswith("MALFORMED")
