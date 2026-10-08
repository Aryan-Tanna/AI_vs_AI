from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lexarena.llm.cache import ResponseCache, request_key
from lexarena.llm.types import ChatMessage, LLMRequest
from lexarena.schemas.config import ModelConfig

BASE_SCHEMA: dict[str, Any] = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}


def _req(**changes: Any) -> LLMRequest:
    model = ModelConfig(
        provider="p",
        family="f",
        name="m",
        temperature=0.0,
        max_output_tokens=64,
        reasoning_effort=None,
        api_key_env="K",
    )
    fields: dict[str, Any] = {
        "model": model,
        "messages": [ChatMessage(role="user", content="hi")],
        "json_schema": BASE_SCHEMA,
        "schema_name": "S",
        "seed": 7,
    }
    fields.update(changes)
    return LLMRequest(**fields)


def _model(**changes: Any) -> ModelConfig:
    return _req().model.model_copy(update=changes)


def test_identical_requests_share_a_key() -> None:
    assert request_key(_req()) == request_key(_req())


@pytest.mark.parametrize(
    "changes",
    [
        {"json_schema": {**BASE_SCHEMA, "properties": {"a": {"type": "string"}}}},  # same name, different schema
        {"schema_name": "T"},
        {"seed": 8},
        {"messages": [ChatMessage(role="user", content="hello")]},
        {"messages": [ChatMessage(role="system", content="hi")]},
        {"model": _model(temperature=0.5)},
        {"model": _model(name="m2")},
        {"model": _model(provider="q")},
        {"model": _model(max_output_tokens=128)},
    ],
    ids=["schema", "schema_name", "seed", "content", "role", "temperature", "model", "provider", "max_tokens"],
)
def test_anything_that_can_change_output_changes_the_key(changes: dict[str, Any]) -> None:
    assert request_key(_req(**changes)) != request_key(_req())


def test_api_key_variable_is_not_part_of_the_key() -> None:
    assert request_key(_req(model=_model(api_key_env="OTHER"))) == request_key(_req())


def test_cache_round_trip(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path / "c.sqlite")
    assert cache.get("k") is None
    cache.put("k", '{"a": 1}')
    assert cache.get("k") == '{"a": 1}'
    cache.close()
    assert ResponseCache(tmp_path / "c.sqlite").get("k") == '{"a": 1}'


def test_an_unset_optional_model_setting_leaves_the_key_unchanged() -> None:
    """Adding `reasoning_effort` (D-081) must not invalidate cached answers of models that do not use it."""
    import hashlib
    import json

    req = _req()
    legacy = {
        "model": req.model.model_dump(exclude={"api_key_env", "reasoning_effort"}),
        "seed": req.seed,
        "schema_name": req.schema_name,
        "schema": req.json_schema,
        "messages": [m.model_dump() for m in req.messages],
    }
    assert request_key(req) == hashlib.sha256(json.dumps(legacy, sort_keys=True).encode("utf-8")).hexdigest()
    low = _req(model=req.model.model_copy(update={"reasoning_effort": "low"}))
    assert request_key(low) != request_key(req)
