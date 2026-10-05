"""Google Gemini generateContent API."""

from __future__ import annotations

import re
from typing import Any

import httpx

from lexarena.llm.errors import ContentBlockedError
from lexarena.llm.providers.base import post_json
from lexarena.llm.types import LLMRequest, LLMResponse
from lexarena.schemas.config import GeminiProviderConfig

CONTEXT_MARKERS = ("exceeds the maximum number of tokens", "input token count")
DELAY = re.compile(r"^\s*([\d.]+)s\s*$")


def _retry_after(response: httpx.Response) -> float | None:
    try:
        details = response.json().get("error", {}).get("details", [])
    except ValueError:
        return None
    for detail in details:
        match = DELAY.match(str(detail.get("retryDelay", "")))
        if match:
            return float(match.group(1))
    return None


class GeminiProvider:
    def __init__(self, config: GeminiProviderConfig, client: httpx.Client) -> None:
        self._config = config
        self._client = client

    def complete(self, request: LLMRequest, api_key: str) -> LLMResponse:
        system = [m.content for m in request.messages if m.role == "system"]
        contents = [
            {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
            for m in request.messages
            if m.role != "system"
        ]
        generation: dict[str, Any] = {
            "temperature": request.model.temperature,
            "seed": request.seed,
            "maxOutputTokens": request.model.max_output_tokens,
            "responseMimeType": "application/json",
        }
        if self._config.json_mode == "json_schema":
            generation["responseJsonSchema"] = request.json_schema
        payload: dict[str, Any] = {"contents": contents, "generationConfig": generation}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}

        url = f"{self._config.base_url.rstrip('/')}/models/{request.model.name}:generateContent"
        data = post_json(
            self._client,
            url,
            {"x-goog-api-key": api_key},
            payload,
            self._config.timeout_s,
            CONTEXT_MARKERS,
            _retry_after,
        )
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates returned")
            raise ContentBlockedError(f"Gemini returned no answer: {reason}")
        candidate = candidates[0]
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        usage = data.get("usageMetadata") or {}
        return LLMResponse(
            text=text,
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
            finish_reason=candidate.get("finishReason"),
        )
