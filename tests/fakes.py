"""Test doubles. Never imported by lexarena/."""

from __future__ import annotations

from dataclasses import dataclass, field

from lexarena.llm.types import LLMRequest, LLMResponse


@dataclass
class FakeProvider:
    """Replays a script of responses or exceptions and records every request it receives."""

    script: list[LLMResponse | Exception]
    requests: list[LLMRequest] = field(default_factory=list)
    api_keys: list[str] = field(default_factory=list)

    def complete(self, request: LLMRequest, api_key: str) -> LLMResponse:
        self.requests.append(request)
        self.api_keys.append(api_key)
        if not self.script:
            raise AssertionError("FakeProvider script exhausted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def text_response(text: str) -> LLMResponse:
    return LLMResponse(text=text, input_tokens=10, output_tokens=5, finish_reason="stop")
