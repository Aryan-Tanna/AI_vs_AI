"""OpenAI-compatible chat completions: Groq today; DeepSeek and Qwen (DashScope) use the same adapter."""

from __future__ import annotations

from typing import Any

import httpx

from lexarena.llm.errors import OutputTruncatedError
from lexarena.llm.providers.base import post_json
from lexarena.llm.types import LLMRequest, LLMResponse
from lexarena.schemas.config import OpenAICompatProviderConfig

TRUNCATED = "length"
CONTEXT_MARKERS = ("context_length_exceeded", "context length", "maximum context")
# A 400 that rejects the model's own sample, not the request: Groq's strict json_schema check (D-083).
GENERATION_MARKERS = ("json_validate_failed", "does not match the expected schema")


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


class OpenAICompatProvider:
    def __init__(self, config: OpenAICompatProviderConfig, client: httpx.Client) -> None:
        self._config = config
        self._client = client

    def complete(self, request: LLMRequest, api_key: str) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": request.model.name,
            "temperature": request.model.temperature,
            "seed": request.seed,
            self._config.max_tokens_param: request.model.max_output_tokens,
            "messages": [m.model_dump() for m in request.messages],
        }
        if request.model.reasoning_effort is not None:
            payload["reasoning_effort"] = request.model.reasoning_effort
        if self._config.json_mode == "json_schema":
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": request.schema_name, "strict": True, "schema": request.json_schema},
            }
        else:
            payload["response_format"] = {"type": "json_object"}

        data = post_json(
            self._client,
            f"{self._config.base_url.rstrip('/')}/chat/completions",
            {"Authorization": f"Bearer {api_key}"},
            payload,
            self._config.timeout_s,
            CONTEXT_MARKERS,
            _retry_after,
            GENERATION_MARKERS,
        )
        choice = data["choices"][0]
        if choice.get("finish_reason") == TRUNCATED:
            raise OutputTruncatedError(
                f"{request.model.name} hit max_output_tokens ({request.model.max_output_tokens})"
            )
        usage = data.get("usage") or {}
        return LLMResponse(
            text=choice["message"].get("content") or "",
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            finish_reason=choice.get("finish_reason"),
        )
