"""D-151: after the verdict, whether the advocates' record held the evidence an EVIDENCE issue turned on. Offline."""

from __future__ import annotations

import json
from typing import Any

from lexarena.evaluator.align import evaluate
from lexarena.evaluator.evidence import EvidenceAvailability, evidence_in_record
from lexarena.llm.client import LLMClient
from lexarena.prompts import PromptStore
from lexarena.secrets import SecretStore
from tests.conftest import PROMPTS_ROOT
from tests.fakes import FakeProvider, fakes_by_role, text_response
from tests.judge_fixtures import CFG, agent_view
from tests.test_evaluator import ISSUES, bench, truth

POINT = "<decisive point the court relied on>"


def llm(answers: list[dict[str, Any]]) -> tuple[LLMClient, FakeProvider]:
    names = {m.api_key_env for m in CFG.models.by_role().values()}
    provider = FakeProvider([text_response(json.dumps(a)) for a in answers])
    cfg, providers = fakes_by_role(CFG, {"verifier": provider})
    client = LLMClient(
        cfg,
        SecretStore(env_file=None, environ={n: "k" for n in names}),
        PromptStore(PROMPTS_ROOT),
        providers=dict(providers),
        cache=None,
        sleep=lambda _: None,
    )
    return client, provider


def evidence_truth() -> Any:
    gt = truth("PETITIONER", {"I1": ("PETITIONER", "LAW"), "I3": ("RESPONDENT", "EVIDENCE")})
    doc = gt.to_document()
    doc["issue_findings"][1]["decisive_points"] = [POINT]
    return type(gt).model_validate(doc)


def check(answer: dict[str, Any]) -> tuple[dict[str, EvidenceAvailability], FakeProvider]:
    client, provider = llm([answer])
    view = agent_view()
    return evidence_in_record(client, PromptStore(PROMPTS_ROOT), CFG, view, evidence_truth(), session_id="S"), provider


def test_only_evidence_issues_are_asked_and_a_record_backed_point_counts() -> None:
    real_id = agent_view().record.stipulated_facts[0].fact_id
    got, provider = check({"verdicts": [{"point": 1, "verdict": "IN_RECORD", "record_ids": [real_id]}]})
    assert got == {"I3": EvidenceAvailability(in_record=True, record_ids=[real_id])}
    assert len(provider.requests) == 1  # I1 (LAW) is never asked about
    sent = provider.requests[0].messages[-1].content
    assert POINT in sent and real_id in sent  # the point against the agent-visible record


def test_an_invented_record_id_or_a_missing_verdict_is_not_in_record() -> None:
    invented, _ = check({"verdicts": [{"point": 1, "verdict": "IN_RECORD", "record_ids": ["F999"]}]})
    assert invented["I3"].in_record is False and invented["I3"].record_ids == []
    missing, _ = check({"verdicts": []})
    assert missing["I3"].in_record is False


def test_an_evidence_issue_counts_only_when_its_evidence_was_in_record() -> None:
    gt = truth("PETITIONER", {"I1": ("PETITIONER", "LAW"), "I3": ("RESPONDENT", "EVIDENCE")})
    held = {"I1": "PETITIONER", "I2": "PETITIONER", "I3": "RESPONDENT"}
    assert evaluate(bench(upholds=held), gt, ISSUES).issue_alignment == 1.0  # I3 not counted
    out = evaluate(bench(upholds=held), gt, ISSUES, {"I3": EvidenceAvailability(False, [])})
    assert out.issue_alignment == 1.0 and out.issues[1].evidence_in_record is False
    wrong = {"I1": "PETITIONER", "I2": "PETITIONER", "I3": "PETITIONER"}
    counted = evaluate(bench(upholds=wrong), gt, ISSUES, {"I3": EvidenceAvailability(True, ["F1"])})
    assert counted.issue_alignment == 0.5 and counted.issues[1].evidence_record_ids == ["F1"]


def test_the_stored_evaluation_never_carries_the_courts_points() -> None:
    """Only yes/no and record IDs leave the check; the sealed decisive points never reach the session document."""
    gt = evidence_truth()
    stored = evaluate(bench(), gt, ISSUES, {"I3": EvidenceAvailability(True, ["F1"])}).model_dump_json()
    assert POINT not in stored and "<sentinel>" not in stored
