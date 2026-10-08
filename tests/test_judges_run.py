"""The bench end to end with scripted models (BUILD_PLAN Step 11; ARCHITECTURE §5; D-048, D-071)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from lexarena.judges.personas import PersonaNotApprovedError, PersonaRegistry
from lexarena.judges.run import Bench
from lexarena.llm.client import LLMClient
from lexarena.llm.errors import RateLimitedError
from lexarena.prompts import PromptStore
from lexarena.schemas.bench import PERSONAS, InvalidOpinion, OpinionDraft
from tests.conftest import PROMPTS_ROOT
from tests.fakes import FakeProvider
from tests.judge_fixtures import (
    CFG,
    HIDDEN_PRECEDENT_UID,
    PRECEDENT_UID,
    SESSION_ID,
    STATUTE,
    client,
    inputs,
    opinion_json,
)
from tests.test_claim_extraction import checklist

CALLS = len(PERSONAS) * 2  # literal-ok: one call per persona and presentation order


def approved(tmp_path: Path) -> PersonaRegistry:
    reg = PersonaRegistry(tmp_path / "review", PromptStore(PROMPTS_ROOT), CFG.prompts)
    for p in PERSONAS:
        reg.approve(p, by="<owner>", today=date(2000, 1, 2))  # literal-ok: placeholder date
    return reg


def no_layer1(*_: Any) -> list[str]:
    return []


def bench(llm: LLMClient, reg: PersonaRegistry, **kwargs: Any) -> Bench:
    kwargs.setdefault("layer1", no_layer1)
    return Bench(llm, PromptStore(PROMPTS_ROOT), CFG, reg, **kwargs)


def sent(provider: FakeProvider, n: int) -> str:
    return provider.requests[n].messages[-1].content


def test_a_unanimous_bench(tmp_path: Path) -> None:
    calls: list[str] = []
    llm, judge, _ = client([opinion_json("RESPONDENT", "RESPONDENT")] * CALLS)
    result = bench(llm, approved(tmp_path)).decide(inputs(calls=calls), session_id=SESSION_ID)
    v = result.verdict
    assert (v.status, v.winner, v.decided_by) == ("DECIDED", "RESPONDENT", "MAJORITY")
    assert [d.judge for d in result.decisions] == list(PERSONAS)
    assert all(d.persona_approved for d in result.decisions)
    assert len(judge.requests) == CALLS
    assert calls == [f"{PRECEDENT_UID}:ratio", f"{HIDDEN_PRECEDENT_UID}:ratio"]  # fetched once, by ID only
    assert any(HIDDEN_PRECEDENT_UID in n for n in result.notes)


def test_prompts_use_counsel_labels_swap_order_and_carry_each_persona(tmp_path: Path) -> None:
    llm, judge, _ = client([opinion_json()] * CALLS)
    bench(llm, approved(tmp_path)).decide(inputs(), session_id=SESSION_ID)
    reg = approved(tmp_path / "other")
    for n, persona in enumerate(PERSONAS):
        first, second = sent(judge, 2 * n), sent(judge, 2 * n + 1)
        assert reg.render(persona).text in first and reg.render(persona).text in second
        assert first.index("=== SUBMISSIONS OF PETITIONER'S COUNSEL") < first.index("=== SUBMISSIONS OF RESPONDENT'S")
        assert second.index("=== SUBMISSIONS OF RESPONDENT'S COUNSEL") < second.index("=== SUBMISSIONS OF PETITIONER'S")
        for text in (first, second):
            assert "LEX_P" not in text and "LEX_D" not in text
            assert f"[{PRECEDENT_UID}]" in text and f"[{HIDDEN_PRECEDENT_UID}]" not in text
    assert judge.requests[0].model.name == CFG.models.judge.name


def test_unapproved_personas_are_refused_before_any_call(tmp_path: Path) -> None:
    llm, judge, _ = client([])
    reg = PersonaRegistry(tmp_path / "review", PromptStore(PROMPTS_ROOT), CFG.prompts)
    with pytest.raises(PersonaNotApprovedError):
        bench(llm, reg).decide(inputs(), session_id=SESSION_ID)
    assert judge.requests == []


def test_unapproved_personas_run_only_when_allowed_and_are_stamped(tmp_path: Path) -> None:
    llm, _, _ = client([opinion_json()] * CALLS)
    reg = PersonaRegistry(tmp_path / "review", PromptStore(PROMPTS_ROOT), CFG.prompts)
    result = bench(llm, reg, allow_unapproved_personas=True).decide(inputs(), session_id=SESSION_ID)
    assert not any(d.persona_approved for d in result.decisions)
    assert sum("UNAPPROVED" in n for n in result.notes) == len(PERSONAS)


def test_one_revision_fixes_an_unknown_id(tmp_path: Path) -> None:
    bad = opinion_json(rule="<statute never shown>")
    llm, judge, _ = client([bad, opinion_json()] + [opinion_json()] * (CALLS - 1))
    result = bench(llm, approved(tmp_path)).decide(inputs(), session_id=SESSION_ID)
    revision = sent(judge, 1)
    assert "UNKNOWN_RULE_ID I1: <statute never shown>" in revision and "only chance to revise" in revision
    first = result.decisions[0].opinions[0]
    assert not isinstance(first, InvalidOpinion) and first.revised
    assert result.verdict.winner == "PETITIONER"


def test_a_problem_left_after_the_revision_makes_the_persona_abstain(tmp_path: Path) -> None:
    bad = opinion_json(rule="<statute never shown>")
    llm, judge, _ = client([bad, bad] + [opinion_json()] * (CALLS - 1))
    result = bench(llm, approved(tmp_path)).decide(inputs(), session_id=SESSION_ID)
    first = result.decisions[0]
    assert (first.status, first.abstain_reason) == ("ABSTAINED", "INVALID_OPINION")
    assert isinstance(first.opinions[0], InvalidOpinion)
    assert len(judge.requests) == CALLS + 1  # exactly one revision, never a second
    assert result.verdict.deciding_judges == ["PURPOSIVIST", "PROCEDURALIST"]


def test_layer1_problems_in_the_stated_law_are_revised(tmp_path: Path) -> None:
    """The real layer 1: the judge misstates the statute's period (14 days in the Law DB); the extractor quotes it;
    the hard error is fed back once; the corrected opinion passes."""
    wrong = opinion_json(finding="The authority must decide within 99 days.")
    extraction: dict[str, Any] = {
        "checklists": [
            checklist(
                STATUTE,
                threshold_amount_id=None,
                threshold_met_quote=None,
                asserts_threshold_met=None,
                procedural_timelines={"adjudication_window_days": 99, "rectification_window_days": None},
                adjudication_window_quote="decide within 99 days",
            )
        ]
    }
    llm, judge, verifier = client(
        [wrong, opinion_json()] + [opinion_json()] * (CALLS - 1),
        [extraction, *([{"checklists": []}] * CALLS)],
    )
    result = Bench(llm, PromptStore(PROMPTS_ROOT), CFG, approved(tmp_path)).decide(inputs(), session_id=SESSION_ID)
    assert "LAYER1 ERR_TIMELINE_MISSTATED" in sent(judge, 1)
    assert result.decisions[0].opinions[0].revised
    assert result.decisions[0].status == "DECIDED"
    assert verifier.requests[0].model.name == CFG.models.verifier.name


def test_an_llm_failure_is_raised_not_turned_into_an_abstention(tmp_path: Path) -> None:
    llm, judge, _ = client([])
    judge.script = [RateLimitedError("quota", retry_after_s=10**6)]  # literal-ok: longer than any backoff
    with pytest.raises(RateLimitedError):
        bench(llm, approved(tmp_path)).decide(inputs(), session_id=SESSION_ID)


def test_order_disagreement_and_tie_break_through_the_service(tmp_path: Path) -> None:
    script = [
        opinion_json("PETITIONER", score=0.9),  # textualist, both orders: petitioner
        opinion_json("PETITIONER", score=0.9),
        opinion_json("RESPONDENT", "RESPONDENT", score=0.9),  # purposivist, both orders: respondent
        opinion_json("RESPONDENT", "RESPONDENT", score=0.9),
        opinion_json("PETITIONER"),  # proceduralist: orders disagree -> abstains
        opinion_json("RESPONDENT", "RESPONDENT"),
    ]
    llm, _, _ = client(script)
    result = bench(llm, approved(tmp_path)).decide(inputs(), session_id=SESSION_ID)
    v = result.verdict
    assert v.abstaining_judges == ["PROCEDURALIST"]
    assert v.votes == {"PETITIONER": 1, "RESPONDENT": 1}
    assert (v.status, v.unstable_reason) == ("UNSTABLE", "UNBROKEN_TIE")  # equal scores: never a guess


def test_the_model_facing_schema_is_strict_json_friendly() -> None:
    schema = OpinionDraft.model_json_schema()
    text = str(schema)
    assert "additionalProperties" in text and "patternProperties" not in text
