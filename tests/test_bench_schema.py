"""The bench schemas (D-048, D-051): every invariant a stored verdict must hold, and older documents still validate."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from lexarena.schemas.bench import BenchVerdict, JudgeDecision, JudgeOpinion, PersonaApproval
from lexarena.schemas.session import Evaluation, Session, aggregate_from
from tests import builders
from tests.bench_builders import SHA, opinion, opinion_pair


def _decision(**overrides: Any) -> dict[str, Any]:
    pair = opinion_pair("PETITIONER", {"I1": "PETITIONER"})
    base: dict[str, Any] = {
        "judge": "TEXTUALIST",
        "persona_prompt": "judges/persona_textualist.v1",
        "persona_sha256": SHA,
        "persona_approved": True,
        "opinions": [o.model_dump() for o in pair.values()],
        "status": "DECIDED",
        "result": "PETITIONER",
        "abstain_reason": None,
        "issue_results": [{"issue_id": "I1", "status": "DECIDED", "upholds": "PETITIONER"}],
        "order_swap_gap": 0.0,
        "advocacy": {"PETITIONER": 0.5, "RESPONDENT": 0.5},
    }
    return {**base, **overrides}


def _verdict(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "status": "DECIDED",
        "winner": "PETITIONER",
        "decided_by": "MAJORITY",
        "unstable_reason": None,
        "votes": {"PETITIONER": 2, "RESPONDENT": 1},
        "deciding_judges": ["TEXTUALIST", "PURPOSIVIST", "PROCEDURALIST"],
        "abstaining_judges": [],
        "dissenting_judges": ["PROCEDURALIST"],
        "issue_findings": [
            {
                "issue_id": "I1",
                "status": "DECIDED",
                "upholds": "PETITIONER",
                "votes": {"PETITIONER": 2, "RESPONDENT": 1, "NEITHER": 0},
                "deciding_judges": ["TEXTUALIST", "PURPOSIVIST", "PROCEDURALIST"],
                "dissenting_judges": ["PROCEDURALIST"],
            }
        ],
        "advocacy": {"PETITIONER": 0.6, "RESPONDENT": 0.4},
    }
    return {**base, **overrides}


# ---------------------------------------------------------------- opinions and judge decisions


def test_opinion_must_score_exactly_the_issues_it_decides() -> None:
    doc = opinion("PETITIONER_FIRST", "PETITIONER", {"I1": "PETITIONER"}).model_dump()
    doc["advocacy"][0]["issue_id"] = "I2"
    with pytest.raises(ValidationError, match="exactly the issues"):
        JudgeOpinion.model_validate(doc)


def test_opinion_rejects_a_duplicated_issue() -> None:
    doc = opinion("PETITIONER_FIRST", "PETITIONER", {"I1": "PETITIONER"}).model_dump()
    doc["issue_decisions"].append(doc["issue_decisions"][0])
    with pytest.raises(ValidationError, match="duplicate issue decisions"):
        JudgeOpinion.model_validate(doc)


def test_issue_decision_needs_a_governing_rule() -> None:
    doc = opinion("PETITIONER_FIRST", "PETITIONER", {"I1": "PETITIONER"}).model_dump()
    doc["issue_decisions"][0]["governing_rule_ids"] = []
    with pytest.raises(ValidationError):
        JudgeOpinion.model_validate(doc)


def test_valid_judge_decision() -> None:
    assert JudgeDecision.model_validate(_decision()).result == "PETITIONER"


def test_judge_decision_needs_one_opinion_per_order() -> None:
    doc = _decision()
    doc["opinions"][1]["order"] = "PETITIONER_FIRST"
    with pytest.raises(ValidationError, match="one opinion per presentation order"):
        JudgeDecision.model_validate(doc)


def test_judge_cannot_decide_a_result_one_order_did_not_reach() -> None:
    pair = opinion_pair(("PETITIONER", "RESPONDENT"), {"I1": "PETITIONER"})
    with pytest.raises(ValidationError, match="both presentation orders"):
        JudgeDecision.model_validate(_decision(opinions=[o.model_dump() for o in pair.values()]))


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "ABSTAINED"},  # result still set, no reason
        {"status": "ABSTAINED", "result": None},  # no reason
        {"abstain_reason": "ORDER_SWAP_DISAGREEMENT"},  # decided yet a reason
        {"persona_sha256": "not-a-hash"},
    ],
)
def test_judge_decision_invariants(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        JudgeDecision.model_validate(_decision(**overrides))


def test_abstained_judge_decision() -> None:
    pair = opinion_pair(("PETITIONER", "RESPONDENT"), {"I1": "PETITIONER"})
    doc = _decision(
        opinions=[o.model_dump() for o in pair.values()],
        status="ABSTAINED",
        result=None,
        abstain_reason="ORDER_SWAP_DISAGREEMENT",
    )
    assert JudgeDecision.model_validate(doc).abstain_reason == "ORDER_SWAP_DISAGREEMENT"


# ---------------------------------------------------------------- bench verdict


def test_valid_bench_verdict() -> None:
    assert BenchVerdict.model_validate(_verdict()).winner == "PETITIONER"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"winner": None}, "exactly when the verdict is DECIDED"),
        ({"unstable_reason": "UNBROKEN_TIE"}, "exactly when the verdict is UNSTABLE"),
        ({"decided_by": "TIE_BREAK"}, "even split"),
        ({"votes": {"PETITIONER": 1, "RESPONDENT": 1}}, "more deciding votes"),
        ({"votes": {"PETITIONER": 2}}, "both sides"),
        ({"abstaining_judges": ["TEXTUALIST"]}, "both decide and abstain"),
    ],
)
def test_bench_verdict_invariants(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        BenchVerdict.model_validate(_verdict(**overrides))


def test_unstable_verdict_has_no_winner_and_a_reason() -> None:
    v = BenchVerdict.model_validate(
        _verdict(
            status="UNSTABLE",
            winner=None,
            decided_by=None,
            unstable_reason="TOO_FEW_DECIDING_JUDGES",
            votes={"PETITIONER": 1, "RESPONDENT": 0},
            deciding_judges=["TEXTUALIST"],
            abstaining_judges=["PURPOSIVIST", "PROCEDURALIST"],
            dissenting_judges=[],
        )
    )
    assert v.winner is None


def test_tie_break_is_allowed_on_an_even_split() -> None:
    v = BenchVerdict.model_validate(
        _verdict(decided_by="TIE_BREAK", votes={"PETITIONER": 1, "RESPONDENT": 1}, dissenting_judges=["PURPOSIVIST"])
    )
    assert v.decided_by == "TIE_BREAK"


# ---------------------------------------------------------------- session


def _session_doc(**overrides: Any) -> dict[str, Any]:
    doc = builders.session("S1", "TESTCASE_0001").to_document()
    return {**doc, **overrides}


def test_pre_step_11_session_documents_still_validate() -> None:
    doc = _session_doc(state="VERDICT_RECORDED", winner="TIE", aggregate={"PETITIONER": 0.5, "RESPONDENT": 0.5})
    session = Session.model_validate(doc)
    assert session.bench is None and session.judge_decisions == []


def test_session_winner_mirrors_the_bench() -> None:
    verdict = BenchVerdict.model_validate(_verdict())
    doc = _session_doc(
        state="VERDICT_RECORDED",
        winner="PETITIONER",
        aggregate=aggregate_from(verdict).model_dump(),
        bench=verdict.model_dump(),
        judge_decisions=[_decision()],
    )
    assert Session.model_validate(doc).winner == "PETITIONER"
    with pytest.raises(ValidationError, match="mirror the bench"):
        Session.model_validate({**doc, "winner": "RESPONDENT"})


def test_unstable_bench_is_stored_as_unstable_winner() -> None:
    verdict = BenchVerdict.model_validate(
        _verdict(
            status="UNSTABLE",
            winner=None,
            decided_by=None,
            unstable_reason="UNBROKEN_TIE",
            votes={"PETITIONER": 1, "RESPONDENT": 1},
            dissenting_judges=[],
        )
    )
    doc = _session_doc(
        state="VERDICT_RECORDED",
        winner="UNSTABLE",
        aggregate=aggregate_from(verdict).model_dump(),
        bench=verdict.model_dump(),
        judge_decisions=[_decision()],
    )
    assert Session.model_validate(doc).winner == "UNSTABLE"


def test_bench_needs_its_judge_decisions_and_vice_versa() -> None:
    verdict = BenchVerdict.model_validate(_verdict())
    recorded = {"state": "VERDICT_RECORDED", "winner": "PETITIONER", "aggregate": aggregate_from(verdict).model_dump()}
    with pytest.raises(ValidationError, match="judge decisions it came from"):
        Session.model_validate(_session_doc(**recorded, bench=verdict.model_dump()))
    with pytest.raises(ValidationError, match="only with the bench verdict"):
        Session.model_validate(_session_doc(**recorded, judge_decisions=[_decision()]))


def test_aggregate_from_an_unscored_bench_is_zero() -> None:
    verdict = BenchVerdict.model_validate(_verdict(advocacy=None))
    assert aggregate_from(verdict).model_dump() == {"PETITIONER": 0.0, "RESPONDENT": 0.0}


def test_pre_step_12_evaluation_still_validates() -> None:
    e = Evaluation.model_validate({"winner_matches_real": None, "issue_alignment": 0.0})
    assert e.issues == [] and e.real_overall is None


# ---------------------------------------------------------------- persona approval


def test_persona_approval_states() -> None:
    draft = {
        "persona": "TEXTUALIST",
        "prompt_id": "judges/persona_textualist.v1",
        "sha256": SHA,
        "status": "DRAFT",
        "decided_by": None,
        "decided_on": None,
        "note": None,
    }
    assert PersonaApproval.model_validate(draft).status == "DRAFT"
    with pytest.raises(ValidationError, match="decided_by"):
        PersonaApproval.model_validate({**draft, "status": "APPROVED"})
    approved = PersonaApproval.model_validate(
        {**draft, "status": "APPROVED", "decided_by": "<owner>", "decided_on": builders.PLACEHOLDER_DATE}
    )
    assert approved.status == "APPROVED"
