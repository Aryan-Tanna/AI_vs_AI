"""The judge validator (ARCHITECTURE §5; SPEC I3-6): every reason cites only what exists and was shown."""

from __future__ import annotations

from typing import Any

from lexarena.judges.validate import Allowed, check_opinion, finalize, normalize_ids
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
    assert any(p.startswith('UNKNOWN_RULE_ID I1: "<statute never shown>"') for p in problems)
    assert any(p.startswith('UNKNOWN_RULE_ID I1: "F1"') for p in problems)  # a record item is not a rule
    assert any(p.startswith('UNKNOWN_RECORD_ID I2: "F99"') for p in problems)


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


# ---------------------------------------------------------------- ID formatting (R-036, DEV4_E2E_2)


def test_bracketed_ids_are_read_as_the_bare_id() -> None:
    """DEV4_E2E_2: the Textualist wrote '[IBC_2016_SEC_60]' and '[F2]' in its ID lists (the prompt cites IDs in square
    brackets in prose). A bracketed ID names exactly one shown ID, so it is read as that ID, not rejected."""
    d = draft(
        "PETITIONER",
        [
            decision("I1", governing_rule_ids=["[<statute A>]", " <precedent uid> "], record_ids=["[F1]", "[EX-1]"]),
            decision("I2"),
        ],
    )
    fixed, n = normalize_ids(d, ALLOWED)
    assert n == 4
    assert fixed.issue_decisions[0].governing_rule_ids == ["<statute A>", "<precedent uid>"]
    assert fixed.issue_decisions[0].record_ids == ["F1", "EX-1"]
    assert check_opinion(fixed, ALLOWED) == []


def test_a_doubled_leading_i_is_read_as_the_shown_id() -> None:
    """DEV4_E2E_2 and _3: Qwen 3.8 Flash wrote 'IIBC_2016_SEC_60' for the shown 'IBC_2016_SEC_60' even after the
    prompt and the revision named the right ID (D-101). A valid ID and an issue ID are never changed."""
    allowed = Allowed(
        issue_ids=["I1", "I2"], statute_ids={"IBC_2016_SEC_60"}, precedent_uids=set(), record_ids={"F2", "IF9"}
    )
    d = draft(
        "PETITIONER",
        [decision("I1", governing_rule_ids=["IIBC_2016_SEC_60", "I1"], record_ids=["IF2", "IF9"]), decision("I2")],
    )
    fixed, n = normalize_ids(d, allowed)
    assert n == 2
    assert fixed.issue_decisions[0].governing_rule_ids == ["IBC_2016_SEC_60", "I1"]
    assert fixed.issue_decisions[0].record_ids == ["F2", "IF9"]  # IF9 is itself shown, so it is kept


def test_an_id_split_into_characters_stays_a_problem() -> None:
    """DEV4_E2E_3: the Proceduralist's ID lists came back one character per entry."""
    d = draft("PETITIONER", [decision("I1", governing_rule_ids=["<", "s"], record_ids=["F", "1"]), decision("I2")])
    fixed, _ = normalize_ids(d, ALLOWED)
    assert any(p.startswith('UNKNOWN_RULE_ID I1: "<"') for p in check_opinion(fixed, ALLOWED))


def test_an_unknown_id_problem_names_the_likely_shown_id() -> None:
    allowed = Allowed(issue_ids=["I1"], statute_ids={"S1"}, precedent_uids=set(), record_ids={"F2"})
    d = draft("PETITIONER", [decision("I1", governing_rule_ids=["XS1"], record_ids=["F2"])])
    assert any('did you mean "S1"' in p for p in check_opinion(d, allowed))


def test_an_issue_id_given_as_a_rule_is_explained() -> None:
    """DEV4_E2E_2: the Purposivist put I1 and I2 in governing_rule_ids."""
    d = draft("PETITIONER", [decision("I1", governing_rule_ids=["I1", "I2"]), decision("I2")])
    problems = check_opinion(d, ALLOWED)
    assert any(p.startswith('UNKNOWN_RULE_ID I1: "I2"') and "issue ID" in p for p in problems)
