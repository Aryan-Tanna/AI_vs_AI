"""Second-family entailment of every record item against its own sources (SPEC I3-8, D-056), with a fake provider.
Placeholder content only."""

from __future__ import annotations

import json
from typing import Any

import pytest

from lexarena.app import PROMPTS_ROOT
from lexarena.clerk.entailment import EntailmentError, check_entailment, entailment_items
from lexarena.config import load_config
from lexarena.llm.client import LLMClient
from lexarena.prompts import PromptStore
from lexarena.schemas.config import AppConfig
from lexarena.secrets import SecretStore
from tests.conftest import CONFIG_V1
from tests.fakes import FakeProvider, text_response
from tests.test_clerk_assemble import build, draft

SOURCES = {"P1": "<p1 text>", "P2": "<p2 text>", "P4.S1": "<sentence>"}


@pytest.fixture
def cfg() -> AppConfig:
    return load_config(CONFIG_V1)


def client(cfg: AppConfig, *answers: dict[str, Any]) -> tuple[LLMClient, FakeProvider]:
    names = {m.api_key_env for m in cfg.models.by_role().values()}
    provider = FakeProvider([text_response(json.dumps(a)) for a in answers])
    llm = LLMClient(
        cfg,
        SecretStore(env_file=None, environ={n: "k" for n in names}),
        PromptStore(PROMPTS_ROOT),
        providers={cfg.models.clerk_secondary.provider: provider},
        cache=None,
        sleep=lambda _: None,
    )
    return llm, provider


def verdicts(ids: list[str], **override: str) -> dict[str, Any]:
    return {"verdicts": [{"item_id": i, "verdict": override.get(i, "SUPPORTED"), "reason": "<r>"} for i in ids]}


def test_every_fact_exhibit_and_ground_becomes_an_item_with_its_own_sources() -> None:
    items = entailment_items(build(draft()).view, SOURCES)
    assert [i.item_id for i in items] == ["F1", "EX-1", "PETITIONER-G1"]
    assert "<p1 text>" in items[0].sources and "<sentence>" in items[1].sources and "<p2 text>" not in items[0].sources


def test_supported_items_pass_and_go_to_the_second_family(cfg: AppConfig) -> None:
    view = build(draft()).view
    llm, provider = client(cfg, verdicts(["F1", "EX-1", "PETITIONER-G1"]))
    problems, flags = check_entailment(llm, PromptStore(PROMPTS_ROOT), cfg, view, SOURCES, session_id="t")
    assert problems == [] and flags == []
    assert provider.requests[0].model.family != cfg.models.clerk_primary.family


def test_not_supported_blocks_and_partly_flags(cfg: AppConfig) -> None:
    view = build(draft()).view
    llm, _ = client(cfg, verdicts(["F1", "EX-1", "PETITIONER-G1"], **{"F1": "NOT_SUPPORTED", "EX-1": "PARTLY"}))
    problems, flags = check_entailment(llm, PromptStore(PROMPTS_ROOT), cfg, view, SOURCES, session_id="t")
    assert len(problems) == 1 and "F1" in problems[0]
    assert [f.code for f in flags] == ["ENTAILMENT_PARTLY"]


def test_a_missing_verdict_is_an_error_not_a_pass(cfg: AppConfig) -> None:
    view = build(draft()).view
    llm, _ = client(cfg, verdicts(["F1", "EX-1"]))
    with pytest.raises(EntailmentError):
        check_entailment(llm, PromptStore(PROMPTS_ROOT), cfg, view, SOURCES, session_id="t")


def test_items_are_batched_within_the_character_budget(cfg: AppConfig) -> None:
    view = build(draft()).view
    small = cfg.model_copy(update={"clerk": cfg.clerk.model_copy(update={"entailment_batch_chars": 10})})
    llm, provider = client(small, verdicts(["F1"]), verdicts(["EX-1"]), verdicts(["PETITIONER-G1"]))
    check_entailment(llm, PromptStore(PROMPTS_ROOT), small, view, SOURCES, session_id="t")
    assert len(provider.requests) == 3
