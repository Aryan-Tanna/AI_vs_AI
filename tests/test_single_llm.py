"""The single-LLM baseline (D-072): one call on the case file, never repaired toward the bench."""

from __future__ import annotations

import json

from lexarena.baselines.single_llm import predict
from lexarena.prompts import PromptStore
from tests.conftest import PROMPTS_ROOT
from tests.judge_fixtures import CFG, STATUTE, agent_view, client
from tests.test_layer1 import statute_view


def answer(issues: list[tuple[str, str]], overall: str = "RESPONDENT") -> str:
    return json.dumps(
        {
            "issue_decisions": [{"issue_id": i, "upholds": u} for i, u in issues],
            "overall_result": overall,
            "reasons": "<reasons>",
        }
    )


def test_prediction_from_one_call_on_the_case_file() -> None:
    llm, judge, _ = client([answer([("I1", "RESPONDENT")])])
    p = predict(llm, PromptStore(PROMPTS_ROOT), CFG, agent_view(), {STATUTE: statute_view(STATUTE)}, session_id="S")
    assert (p.overall, p.issues, p.problems) == ("RESPONDENT", {"I1": "RESPONDENT"}, [])
    assert len(judge.requests) == 1
    sent = judge.requests[0].messages[-1].content
    assert f"[{STATUTE}]" in sent and "[F1]" in sent and "LEX_P" not in sent and "SUBMISSIONS" not in sent
    assert p.model == CFG.models.by_role()[CFG.evaluation.single_llm_role].name


def test_unknown_missing_and_repeated_issues_are_not_predictions() -> None:
    llm, _, _ = client([answer([("I9", "PETITIONER"), ("I1", "PETITIONER"), ("I1", "RESPONDENT")])])
    p = predict(llm, PromptStore(PROMPTS_ROOT), CFG, agent_view(), {}, session_id="S")
    assert p.issues == {}
    assert p.problems == ["UNKNOWN_ISSUE I9", "DUPLICATE_ISSUE I1"]
