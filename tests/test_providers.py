from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from lexarena.llm.errors import (
    ContentBlockedError,
    ContextBudgetExceededError,
    ProviderRequestError,
    ProviderUnavailableError,
    RateLimitedError,
)
from lexarena.llm.providers.gemini import GeminiProvider
from lexarena.llm.providers.openai_compat import OpenAICompatProvider
from lexarena.llm.types import ChatMessage, LLMRequest
from lexarena.schemas.config import GeminiProviderConfig, ModelConfig, OpenAICompatProviderConfig

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "integer"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def _request(provider: str, json_mode_model: str = "m") -> LLMRequest:
    model = ModelConfig(
        provider=provider, family="f", name=json_mode_model, temperature=0.0, max_output_tokens=64, api_key_env="K"
    )
    return LLMRequest(
        model=model,
        seed=7,
        json_schema=SCHEMA,
        schema_name="Answer",
        messages=[ChatMessage(role="system", content="sys"), ChatMessage(role="user", content="hi")],
    )


def _openai(
    handler: Callable[[httpx.Request], httpx.Response],
    json_mode: str = "json_schema",
    max_tokens_param: str = "max_completion_tokens",
) -> OpenAICompatProvider:
    cfg = OpenAICompatProviderConfig(
        kind="openai_compatible",
        base_url="https://api.example/v1",
        json_mode=json_mode,
        max_tokens_param=max_tokens_param,
        timeout_s=5,
    )
    return OpenAICompatProvider(cfg, httpx.Client(transport=httpx.MockTransport(handler)))


def _gemini(handler: Callable[[httpx.Request], httpx.Response], json_mode: str = "json_schema") -> GeminiProvider:
    cfg = GeminiProviderConfig(kind="gemini", base_url="https://gem.example/v1beta", json_mode=json_mode, timeout_s=5)
    return GeminiProvider(cfg, httpx.Client(transport=httpx.MockTransport(handler)))


def _ok_openai(content: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3},
    }


# ---------- OpenAI-compatible (Groq now; DeepSeek and Qwen later) ----------


def test_openai_payload_and_parsing() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=_ok_openai('{"answer": 1}'))

    resp = _openai(handler).complete(_request("p"), api_key="sk-test")
    assert seen["url"] == "https://api.example/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test"
    body = seen["body"]
    assert body["model"] == "m" and body["temperature"] == 0.0 and body["seed"] == 7
    assert body["max_completion_tokens"] == 64
    assert body["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "Answer", "strict": True, "schema": SCHEMA},
    }
    assert resp.text == '{"answer": 1}' and resp.input_tokens == 11 and resp.output_tokens == 3


def test_openai_json_object_mode_and_max_tokens_name() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=_ok_openai("{}"))

    _openai(handler, json_mode="json_object", max_tokens_param="max_tokens").complete(_request("p"), api_key="k")
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["max_tokens"] == 64 and "max_completion_tokens" not in seen["body"]


@pytest.mark.parametrize(
    ("status", "body", "headers", "error"),
    [
        (413, {"error": {"message": "Request too large"}}, {}, ContextBudgetExceededError),
        (400, {"error": {"code": "context_length_exceeded", "message": "too long"}}, {}, ContextBudgetExceededError),
        (429, {"error": {"message": "rate"}}, {"retry-after": "12"}, RateLimitedError),
        (503, {"error": {"message": "busy"}}, {}, ProviderUnavailableError),
        (500, {"error": {"message": "oops"}}, {}, ProviderUnavailableError),
        (400, {"error": {"message": "bad"}}, {}, ProviderRequestError),
        (401, {"error": {"message": "auth"}}, {}, ProviderRequestError),
    ],
)
def test_openai_error_mapping(status: int, body: dict[str, Any], headers: dict[str, str], error: type) -> None:
    provider = _openai(lambda req: httpx.Response(status, json=body, headers=headers))
    with pytest.raises(error) as exc:
        provider.complete(_request("p"), api_key="k")
    if error is RateLimitedError:
        assert isinstance(exc.value, RateLimitedError) and exc.value.retry_after_s == 12


def test_openai_timeout_is_retryable() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(ProviderUnavailableError):
        _openai(handler).complete(_request("p"), api_key="k")


def test_openai_error_message_never_contains_key() -> None:
    provider = _openai(lambda req: httpx.Response(400, json={"error": {"message": "bad"}}))
    with pytest.raises(ProviderRequestError) as exc:
        provider.complete(_request("p"), api_key="sk-super-secret")
    assert "sk-super-secret" not in str(exc.value)


# ---------- Gemini ----------


def _ok_gemini(parts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "candidates": [{"content": {"parts": parts}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 21, "candidatesTokenCount": 4},
    }


def test_gemini_payload_and_parsing() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["key"] = req.headers["x-goog-api-key"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(
            200, json=_ok_gemini([{"text": "thinking...", "thought": True}, {"text": '{"answer": 2}'}])
        )

    resp = _gemini(handler).complete(_request("g", "gemini-x"), api_key="g-key")
    assert seen["url"] == "https://gem.example/v1beta/models/gemini-x:generateContent"
    assert seen["key"] == "g-key"
    body = seen["body"]
    assert body["systemInstruction"] == {"parts": [{"text": "sys"}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": "hi"}]}]
    gen = body["generationConfig"]
    assert gen["temperature"] == 0.0 and gen["seed"] == 7 and gen["maxOutputTokens"] == 64
    assert gen["responseMimeType"] == "application/json" and gen["responseJsonSchema"] == SCHEMA
    assert resp.text == '{"answer": 2}' and resp.input_tokens == 21 and resp.output_tokens == 4


def test_gemini_assistant_turns_become_model_role() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=_ok_gemini([{"text": "{}"}]))

    req = _request("g")
    req = req.model_copy(
        update={
            "messages": [
                *req.messages,
                ChatMessage(role="assistant", content="prev"),
                ChatMessage(role="user", content="fix"),
            ]
        }
    )
    _gemini(handler).complete(req, api_key="k")
    assert [c["role"] for c in seen["body"]["contents"]] == ["user", "model", "user"]


def test_gemini_json_object_mode_omits_schema() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=_ok_gemini([{"text": "{}"}]))

    _gemini(handler, json_mode="json_object").complete(_request("g"), api_key="k")
    assert "responseJsonSchema" not in seen["body"]["generationConfig"]


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (
            429,
            {
                "error": {
                    "message": "quota",
                    "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "30s"}],
                }
            },
            RateLimitedError,
        ),
        (503, {"error": {"message": "high demand"}}, ProviderUnavailableError),
        (
            400,
            {"error": {"message": "The input token count exceeds the maximum number of tokens allowed"}},
            ContextBudgetExceededError,
        ),
        (400, {"error": {"message": "bad"}}, ProviderRequestError),
    ],
)
def test_gemini_error_mapping(status: int, body: dict[str, Any], error: type) -> None:
    with pytest.raises(error) as exc:
        _gemini(lambda req: httpx.Response(status, json=body)).complete(_request("g"), api_key="k")
    if error is RateLimitedError:
        assert isinstance(exc.value, RateLimitedError) and exc.value.retry_after_s == 30


def test_gemini_blocked_prompt_is_not_retryable() -> None:
    body = {"promptFeedback": {"blockReason": "SAFETY"}}
    with pytest.raises(ContentBlockedError):
        _gemini(lambda req: httpx.Response(200, json=body)).complete(_request("g"), api_key="k")
