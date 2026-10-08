"""THEMIS-LOCAL claim extraction (BUILD_PLAN Step 7; SPEC D1; D-062). Offline, with a scripted model.

Code holds the model's extraction to the argument: unknown statutes are dropped, quotes not in the argument lose
their confidence (so the audit marks them UNMAPPED), unknown readings and amount IDs are dropped.
"""

from __future__ import annotations

import json
from typing import Any

from lexarena.config import load_config
from lexarena.llm.client import LLMClient
from lexarena.prompts import PromptStore
from lexarena.schemas.themis import ArgumentExtraction
from lexarena.secrets import SecretStore
from lexarena.themis_local.extract import ROLE, extract_checklists
from tests.conftest import CONFIG_V1, PROMPTS_ROOT
from tests.fakes import FakeProvider, text_response
from tests.test_layer1 import FACTS, statute_view

CFG = load_config(CONFIG_V1)
ARGUMENT = "The demand notice was served on the debtor.  The default of AM1 does not cross the minimum."


def client(answer: dict[str, Any]) -> tuple[LLMClient, FakeProvider]:
    names = {m.api_key_env for m in CFG.models.by_role().values()}
    provider = FakeProvider([text_response(json.dumps(answer))])
    role = CFG.models.by_role()[ROLE]
    llm = LLMClient(
        CFG,
        SecretStore(env_file=None, environ={n: "k" for n in names}),
        PromptStore(PROMPTS_ROOT),
        providers={role.provider: provider},
        cache=None,
        sleep=lambda _: None,
    )
    return llm, provider


def checklist(statute_id: str, **change: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "statute_id": statute_id,
        "stance": "INVOKE_BAR",
        "asserts_threshold_met": False,
        "threshold_amount_id": "AM1",
        "chosen_readings": [],
        "asserts_within_limitation": None,
        "acknowledgment_dates": [],
        "diagnostic_checklist": {
            "applicant_eligibility": [],
            "financial_threshold": {"minimum_amount": None, "currency": None},
            "mandatory_prerequisites": [
                {"law_index": 0, "quote": "the demand notice was SERVED on the debtor.", "confidence": 0.9},
                {"law_index": 1, "quote": "the notice was received by fax", "confidence": 0.9},
            ],
            "statutory_bars": [],
            "saving_exceptions": [],
        },
        "procedural_timelines": {"adjudication_window_days": None, "rectification_window_days": None},
    }
    base.update(change)
    return base


def run(answer: dict[str, Any]) -> Any:
    llm, provider = client(answer)
    views = {"A_SEC_1": statute_view("A_SEC_1")}
    report = extract_checklists(
        llm, PromptStore(PROMPTS_ROOT), CFG, ARGUMENT, views, {}, FACTS.amounts, session_id="S-TEST"
    )
    return report, provider


def test_quotes_are_held_to_the_argument() -> None:
    report, provider = run({"checklists": [checklist("A_SEC_1")]})
    items = report.checklists[0].diagnostic_checklist.mandatory_prerequisites
    assert [i.confidence for i in items] == [0.9, 0.0]  # whitespace and case aside the first is verbatim
    sent = provider.requests[0].messages[-1].content
    assert "A_SEC_1" in sent and ARGUMENT in sent and provider.requests[0].model.temperature == 0


def test_a_statute_that_was_not_offered_is_dropped() -> None:
    report, _ = run({"checklists": [checklist("A_SEC_1"), checklist("INVENTED_SEC_99")]})
    assert [c.statute_id for c in report.checklists] == ["A_SEC_1"]
    assert any("INVENTED_SEC_99" in n for n in report.notes)


def test_unknown_amounts_and_readings_are_dropped() -> None:
    report, _ = run(
        {
            "checklists": [
                checklist("A_SEC_1", threshold_amount_id="AM7", chosen_readings=[{"parameter": "x", "option": "y"}])
            ]
        }
    )
    assert report.checklists[0].threshold_amount_id is None and report.checklists[0].chosen_readings == {}


def test_no_statutes_means_no_call() -> None:
    llm, provider = client({"checklists": []})
    report = extract_checklists(llm, PromptStore(PROMPTS_ROOT), CFG, ARGUMENT, {}, {}, {}, session_id="S-TEST")
    assert report.checklists == [] and provider.requests == []


def _nodes(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found += _nodes(value)
    elif isinstance(node, list):
        for value in node:
            found += _nodes(value)
    return found


def test_the_extraction_schema_passes_strict_json_modes() -> None:
    # Groq's strict mode refused an int|float union and a free-form map (measured 2026-10-08).
    for node in _nodes(ArgumentExtraction.model_json_schema()):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False and "properties" in node, node
        types = {branch.get("type") for branch in node.get("anyOf", [])}
        assert not {"integer", "number"} <= types, node
