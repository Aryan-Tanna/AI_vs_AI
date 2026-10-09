"""Test doubles. Never imported by lexarena/."""

from __future__ import annotations

from dataclasses import dataclass, field

from lexarena.llm.types import LLMRequest, LLMResponse
from lexarena.schemas.config import AppConfig


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


def fakes_by_role(cfg: AppConfig, fakes: dict[str, FakeProvider]) -> tuple[AppConfig, dict[str, FakeProvider]]:
    """Gives each named role its own provider name, so a test can script it separately even when the production
    config serves several roles through one gateway. Only provider names change; models, keys and the rest stay."""
    providers = dict(cfg.providers)
    models = {}
    for role in fakes:
        model = getattr(cfg.models, role)
        providers[f"fake-{role}"] = cfg.providers[model.provider]
        models[role] = model.model_copy(update={"provider": f"fake-{role}"})
    split = cfg.model_copy(update={"models": cfg.models.model_copy(update=models), "providers": providers})
    return split, {f"fake-{role}": fake for role, fake in fakes.items()}


def text_response(text: str) -> LLMResponse:
    return LLMResponse(text=text, input_tokens=10, output_tokens=5, finish_reason="stop")


class WordEmbedder:
    """Deterministic stand-in for the embedding model: one token per word, a small hashed vector per text."""

    dim = 8

    def __init__(self) -> None:
        self.calls = 0

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def embed(self, texts: list[str]) -> list[list[float]]:
        import hashlib

        self.calls += 1
        out = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vector = [b / 255 + 0.01 for b in digest[: self.dim]]
            out.append(vector)
        return out
