"""Clerk model steps (BUILD_PLAN Step 6, D-056): entity listing and paragraph routing, with a fake provider.
Code checks every model answer; nothing is guessed when the answer is incomplete. Placeholder text only."""

from __future__ import annotations

import json
from typing import Any

import pytest

from lexarena.app import PROMPTS_ROOT
from lexarena.clerk.steps import (
    RouteError,
    list_entities,
    render_paragraphs,
    route_paragraphs,
    select_record_facts,
    split_sentences,
)
from lexarena.config import load_config
from lexarena.llm.client import LLMClient
from lexarena.prompts import PromptStore
from lexarena.schemas.config import AppConfig
from lexarena.schemas.judgment import JudgmentParagraph
from lexarena.secrets import SecretStore
from tests.conftest import CONFIG_V1
from tests.fakes import FakeProvider, text_response


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
        providers={cfg.models.clerk_primary.provider: provider},
        cache=None,
        sleep=lambda _: None,
    )
    return llm, provider


def paras(n: int) -> list[JudgmentParagraph]:
    return [JudgmentParagraph(para_id=f"P{i}", court_no=str(i), page=1, text=f"<text {i}>") for i in range(1, n + 1)]


def test_routing_labels_every_paragraph(cfg: AppConfig) -> None:
    llm, _ = client(cfg, {"labels": [{"para_id": "P1", "part": "FACTS"}, {"para_id": "P2", "part": "ANALYSIS"}]})
    assert route_paragraphs(llm, PromptStore(PROMPTS_ROOT), cfg, paras(2), session_id="t") == {
        "P1": "FACTS",
        "P2": "ANALYSIS",
    }


@pytest.mark.parametrize(
    "labels",
    [
        [{"para_id": "P1", "part": "FACTS"}],  # P2 missing
        [{"para_id": "P1", "part": "FACTS"}, {"para_id": "P1", "part": "ANALYSIS"}, {"para_id": "P2", "part": "FACTS"}],
        [{"para_id": "P1", "part": "FACTS"}, {"para_id": "P2", "part": "FACTS"}, {"para_id": "P9", "part": "FACTS"}],
    ],
)
def test_incomplete_or_inconsistent_routing_is_refused(cfg: AppConfig, labels: list[dict[str, str]]) -> None:
    llm, _ = client(cfg, {"labels": labels})
    with pytest.raises(RouteError):
        route_paragraphs(llm, PromptStore(PROMPTS_ROOT), cfg, paras(2), session_id="t")


def test_router_sees_the_opening_of_long_paragraphs_only() -> None:
    long = JudgmentParagraph(para_id="P1", court_no="1", page=1, text="x" * 50 + "<hidden tail>")
    rendered = render_paragraphs([long], chars=50)
    assert rendered.startswith("[P1] ") and "<hidden tail>" not in rendered and rendered.endswith("…")


def test_entities_come_back_as_listed(cfg: AppConfig) -> None:
    answer = {"entities": [{"name": "<Name One>", "variants": ["<N1>"], "kind": "COMPANY"}]}
    llm, provider = client(cfg, answer)
    [entity] = list_entities(llm, PromptStore(PROMPTS_ROOT), cfg, "<header>", paras(1), session_id="t")
    assert entity.name == "<Name One>" and entity.variants == ["<N1>"]
    sent = provider.requests[0].messages[-1].content
    assert "<header>" in sent and "<text 1>" in sent  # the whole text: variants can appear anywhere


# ---------------------------------------------------------------- record facts stated inside the reasoning


def test_sentences_split_on_full_stops_but_not_on_abbreviations() -> None:
    text = "The Co. paid Rs. 5 to M/s. X Pvt. Ltd. on 01.01.2001. It sued under Sec. 7 i.e. the Code. Next one."
    assert split_sentences(text) == [
        "The Co. paid Rs. 5 to M/s. X Pvt. Ltd. on 01.01.2001.",
        "It sued under Sec. 7 i.e. the Code.",
        "Next one.",
    ]


def analysis_para() -> JudgmentParagraph:
    return JudgmentParagraph(
        para_id="P4",
        court_no="4",
        page=1,
        text="The date of default is recorded as <date one>. We are of the view that it is barred. "
        "The creditor went to <forum> on <date two>. The claim is hopelessly late.",
    )


def test_record_fact_sentences_are_kept_with_their_paragraph(cfg: AppConfig) -> None:
    llm, provider = client(cfg, {"record_fact_ids": ["P4.S1", "P4.S3"]})
    kept, flags = select_record_facts(llm, PromptStore(PROMPTS_ROOT), cfg, [analysis_para()], session_id="t")
    assert [(s.para_id, s.text) for s in kept] == [
        ("P4", "The date of default is recorded as <date one>."),
        ("P4", "The creditor went to <forum> on <date two>."),
    ]
    assert flags == []
    assert "[P4.S2] We are of the view" in provider.requests[0].messages[-1].content


def test_a_picked_sentence_in_the_courts_voice_or_evaluative_is_dropped_and_flagged(cfg: AppConfig) -> None:
    llm, _ = client(cfg, {"record_fact_ids": ["P4.S1", "P4.S2", "P4.S4"]})
    kept, flags = select_record_facts(llm, PromptStore(PROMPTS_ROOT), cfg, [analysis_para()], session_id="t")
    assert [s.sentence_id for s in kept] == ["P4.S1"]
    assert [f.code for f in flags] == ["REASONING_DROPPED", "REASONING_DROPPED"]


def test_unknown_sentence_ids_are_refused(cfg: AppConfig) -> None:
    llm, _ = client(cfg, {"record_fact_ids": ["P4.S9"]})
    with pytest.raises(RouteError):
        select_record_facts(llm, PromptStore(PROMPTS_ROOT), cfg, [analysis_para()], session_id="t")
