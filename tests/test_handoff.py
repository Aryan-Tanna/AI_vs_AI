"""The file-exchange provider (D-127): a pilot-only clerk model answered by a Claude Code agent through files, so the
answer passes the same schema validation, cache, call log and clerk checks as any provider's."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from lexarena.config import load_config
from lexarena.llm.cache import ResponseCache
from lexarena.llm.client import LLMClient
from lexarena.llm.errors import HandoffPendingError
from lexarena.llm.providers.handoff import HandoffProvider, pending_prompts
from lexarena.prompts import PromptStore
from lexarena.schemas.config import AppConfig, HandoffProviderConfig
from lexarena.secrets import SecretStore
from tests.conftest import CONFIG_V1, PROMPTS_ROOT


class DaysAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: int


def _setup(tmp_path: Path) -> tuple[AppConfig, LLMClient, Path]:
    raw = load_config(CONFIG_V1)
    exchange = tmp_path / "handoff"
    providers = dict(raw.providers)
    providers["claude_handoff"] = HandoffProviderConfig(kind="handoff", exchange_dir=exchange.as_posix())
    cfg = raw.model_copy(update={"providers": providers}).with_clerk_handoff()
    client = LLMClient(
        cfg,
        SecretStore(env_file=None, environ={}),  # no key at all: the handoff provider needs none
        PromptStore(PROMPTS_ROOT),
        providers={"claude_handoff": HandoffProvider(cfg.providers["claude_handoff"])},  # type: ignore[arg-type]
        cache=ResponseCache(tmp_path / "cache.sqlite"),
    )
    return cfg, client, exchange


def _call(client: LLMClient) -> DaysAnswer:
    prompt = PromptStore(PROMPTS_ROOT).render("smoke/dummy", 1)
    return client.complete_json(role="clerk_primary", user=prompt, schema=DaysAnswer, session_id="clerk-T").value


def test_with_clerk_handoff_swaps_only_the_primary_and_extractor() -> None:
    cfg = load_config(CONFIG_V1)
    swapped = cfg.with_clerk_handoff()
    assert swapped.models.clerk_primary == cfg.models.clerk_handoff
    assert swapped.models.clerk_extractor == cfg.models.clerk_handoff
    # The second-family entailment check and every other role are untouched.
    for role, model in cfg.models.by_role().items():
        if role not in ("clerk_primary", "clerk_extractor"):
            assert swapped.models.by_role()[role] == model


def test_a_missing_answer_writes_the_prompt_and_stops(tmp_path: Path) -> None:
    _, client, exchange = _setup(tmp_path)
    with pytest.raises(HandoffPendingError):
        _call(client)
    [pending] = pending_prompts(exchange)
    body = json.loads(pending.read_text(encoding="utf-8"))
    assert body["schema_name"] == "DaysAnswer"
    assert body["json_schema"] == DaysAnswer.model_json_schema()
    assert body["messages"][-1]["role"] == "user"
    assert body["answer_file"].endswith(".answer.json")


def test_a_written_answer_is_validated_and_cached(tmp_path: Path) -> None:
    _, client, exchange = _setup(tmp_path)
    with pytest.raises(HandoffPendingError):
        _call(client)
    [pending] = pending_prompts(exchange)
    Path(json.loads(pending.read_text(encoding="utf-8"))["answer_file"]).write_text('{"answer": 7}', encoding="utf-8")
    assert pending_prompts(exchange) == []
    assert _call(client) == DaysAnswer(answer=7)
    # Second call is a cache hit even with the exchange folder gone.
    for f in exchange.iterdir():
        f.unlink()
    assert _call(client) == DaysAnswer(answer=7)


def test_an_invalid_answer_goes_through_schema_repair(tmp_path: Path) -> None:
    """A wrong answer is not patched: the client's repair round asks again, which is a new pending prompt."""
    _, client, exchange = _setup(tmp_path)
    with pytest.raises(HandoffPendingError):
        _call(client)
    [first] = pending_prompts(exchange)
    Path(json.loads(first.read_text(encoding="utf-8"))["answer_file"]).write_text('{"answer": "x"}', encoding="utf-8")
    with pytest.raises(HandoffPendingError):
        _call(client)
    [repair] = pending_prompts(exchange)
    messages = json.loads(repair.read_text(encoding="utf-8"))["messages"]
    assert messages[-2] == {"role": "assistant", "content": '{"answer": "x"}'}


def test_the_handoff_model_is_free_and_of_another_family_than_the_checker() -> None:
    cfg = load_config(CONFIG_V1)
    h = cfg.models.clerk_handoff
    assert cfg.providers[h.provider].kind == "handoff"
    assert h.family not in (cfg.models.clerk_secondary.family, cfg.models.lawyer.family)
    assert h.temperature == 0
    free = {(p.provider, p.model) for p in cfg.runner.prices if p.input_usd_per_m == 0 and p.output_usd_per_m == 0}
    assert (h.provider, h.name) in free
