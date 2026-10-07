from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

from lexarena.schemas.config import ModelConfig

T = TypeVar("T", bound=BaseModel)


class ChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str


class LLMRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: ModelConfig
    messages: list[ChatMessage]
    json_schema: dict[str, Any]
    schema_name: str
    seed: int


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    input_tokens: int | None
    output_tokens: int | None
    finish_reason: str | None


@dataclass(frozen=True)
class LLMResult(Generic[T]):
    value: T
    attempts: int
    cached: bool
    input_tokens: int | None
    output_tokens: int | None
