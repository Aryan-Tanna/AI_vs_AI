"""Shared fixtures for the judges tests: an agent view, a two-turn transcript, statute views, scripted models."""

from __future__ import annotations

import json
from typing import Any

from lexarena.config import load_config
from lexarena.judges.packet import PrecedentFetcher
from lexarena.judges.run import BenchInputs, BenchLaw
from lexarena.llm.client import LLMClient
from lexarena.llm.types import LLMResponse
from lexarena.prompts import PromptStore
from lexarena.schemas.base import Side
from lexarena.schemas.case import AgentCaseView
from lexarena.schemas.retrieval import PrecedentExcerpt
from lexarena.schemas.transcript import PublishedTurn
from lexarena.secrets import SecretStore
from tests import builders
from tests.conftest import CONFIG_V1, PROMPTS_ROOT
from tests.fakes import FakeProvider, text_response
from tests.test_layer1 import statute_view

CFG = load_config(CONFIG_V1)
CASE_ID = "TESTCASE_0001"
SESSION_ID = "TESTCASE_0001_R1"
STATUTE = "<statute id>"
PRECEDENT_UID = "<precedent uid>"
HIDDEN_PRECEDENT_UID = "<excluded precedent uid>"


def agent_view() -> AgentCaseView:
    doc = builders.case_doc(CASE_ID)["agent_view"]
    doc["metadata"].pop("simulation_date")
    return AgentCaseView.model_validate({**doc, "case_id": CASE_ID})


def turns(*, flagged: bool = False) -> list[PublishedTurn]:
    out = []
    for n, side in ((1, "PETITIONER"), (2, "RESPONDENT")):
        doc = builders.published_turn(SESSION_ID, CASE_ID, n, side).to_document()  # type: ignore[arg-type]
        doc["published_text"] = f"<argument of turn {n}>"
        doc["claims"][0]["precedent_ids"] = [PRECEDENT_UID, HIDDEN_PRECEDENT_UID] if n == 1 else []
        doc["claims"][0]["statute_id"] = STATUTE
        if flagged and n == 2:
            doc["visible_flags"] = [{"code": "ERR_FACT_NOT_IN_RECORD", "claim_ids": ["C1"], "record_ids": ["F1"]}]
        out.append(PublishedTurn.model_validate(doc))
    return out


def fetcher(calls: list[str]) -> PrecedentFetcher:
    """The judge's get_precedent: the excluded precedent comes back None, as the scoped reader returns it."""

    def get_precedent(uid: str, part: str = "ratio") -> PrecedentExcerpt | None:
        calls.append(f"{uid}:{part}")
        if uid != PRECEDENT_UID:
            return None
        return PrecedentExcerpt(
            precedent_uid=uid,
            precedent_id="<precedent id>",
            case_title="<precedent title>",
            decision_date=builders.PLACEHOLDER_DATE,
            part="ratio",
            text="<ratio text>",
        )

    return get_precedent


def inputs(*, flagged: bool = False, calls: list[str] | None = None) -> BenchInputs:
    return BenchInputs(
        case=agent_view(),
        turns=turns(flagged=flagged),
        law=BenchLaw(views={STATUTE: statute_view(STATUTE)}, alternatives=None, predicates={}),
        fetch_precedent=fetcher(calls if calls is not None else []),
    )


def opinion_json(
    result: Side = "PETITIONER",
    upholds: str = "PETITIONER",
    *,
    rule: str = STATUTE,
    finding: str = "<finding>",
    score: float = 0.5,
) -> str:
    dims = {"accuracy": score, "consistency": score, "rebuttal": score, "grounding": score}
    return json.dumps(
        {
            "issue_decisions": [
                {
                    "issue_id": "I1",
                    "finding": finding,
                    "governing_rule_ids": [rule],
                    "record_ids": ["F1"],
                    "application": "<application>",
                    "conclusion": "<conclusion>",
                    "upholds": upholds,
                }
            ],
            "overall_result": result,
            "overall_reasons": "<reasons>",
            "advocacy": [{"issue_id": "I1", "petitioner": dims, "respondent": dims}],
        }
    )


def client(
    judge_script: list[str], verifier_script: list[dict[str, Any]] | None = None
) -> tuple[LLMClient, FakeProvider, FakeProvider]:
    names = {m.api_key_env for m in CFG.models.by_role().values()}
    judge = FakeProvider([text_response(t) for t in judge_script])
    verifier_responses: list[LLMResponse | Exception] = [text_response(json.dumps(v)) for v in verifier_script or []]
    verifier = FakeProvider(verifier_responses)
    models = CFG.models.by_role()
    llm = LLMClient(
        CFG,
        SecretStore(env_file=None, environ={n: "k" for n in names}),
        PromptStore(PROMPTS_ROOT),
        providers={models["judge"].provider: judge, models["verifier"].provider: verifier},
        cache=None,
        sleep=lambda _: None,
    )
    return llm, judge, verifier
