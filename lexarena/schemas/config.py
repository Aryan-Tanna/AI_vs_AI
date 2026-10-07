"""Pydantic models for config/config.vN.yaml (DATA_FORMATS §6).

Every field is required: values live in the versioned YAML, never in code (non-negotiable 4).
Validators enforce invariants from CLAUDE.md and SPEC I3-7, not tuning choices.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

UnitInterval = Annotated[float, Field(ge=0, le=1)]
PositiveInt = Annotated[int, Field(gt=0)]
PositiveFloat = Annotated[float, Field(gt=0)]
EnvVarName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OpenAICompatProviderConfig(Strict):
    """Any OpenAI-compatible chat API: Groq now, DeepSeek and Qwen (DashScope) later."""

    kind: Literal["openai_compatible"]
    base_url: str
    json_mode: Literal["json_schema", "json_object"]
    max_tokens_param: Literal["max_tokens", "max_completion_tokens"]
    timeout_s: PositiveFloat


class GeminiProviderConfig(Strict):
    kind: Literal["gemini"]
    base_url: str
    json_mode: Literal["json_schema", "json_object"]
    timeout_s: PositiveFloat


ProviderConfig = Annotated[OpenAICompatProviderConfig | GeminiProviderConfig, Field(discriminator="kind")]


class ModelConfig(Strict):
    provider: str
    family: str
    name: str
    temperature: Annotated[float, Field(ge=0)]
    max_output_tokens: PositiveInt
    api_key_env: EnvVarName


class ModelsConfig(Strict):
    lawyer: ModelConfig
    verifier: ModelConfig
    judge: ModelConfig
    auditor: ModelConfig
    clerk_primary: ModelConfig
    clerk_secondary: ModelConfig
    reflection: ModelConfig

    def by_role(self) -> dict[str, ModelConfig]:
        return {name: getattr(self, name) for name in type(self).model_fields}

    @model_validator(mode="after")
    def _invariants(self) -> ModelsConfig:
        # SPEC I3-7: THEMIS (layer 2 and global) must not share the lawyers' model family.
        for role in ("verifier", "auditor"):
            if getattr(self, role).family == self.lawyer.family:
                raise ValueError(f"models.{role}.family must differ from models.lawyer.family (SPEC I3-7)")
        # Two-model agreement in the clerk (ARCHITECTURE §3) needs independent families.
        if self.clerk_primary.family == self.clerk_secondary.family:
            raise ValueError("models.clerk_primary.family must differ from models.clerk_secondary.family")
        # CLAUDE.md: verifiers and extractors run at temperature 0.
        for role in ("verifier", "auditor", "clerk_primary", "clerk_secondary"):
            if getattr(self, role).temperature != 0:
                raise ValueError(f"models.{role}.temperature must be 0 (verifiers and extractors are deterministic)")
        return self


class PromptRef(Strict):
    id: str
    version: PositiveInt


class PromptsConfig(Strict):
    schema_repair: PromptRef
    smoke: PromptRef


class LLMConfig(Strict):
    max_attempts: PositiveInt
    backoff_initial_s: PositiveFloat
    backoff_multiplier: Annotated[float, Field(ge=1)]
    backoff_max_s: PositiveFloat
    cache_enabled: bool
    cache_path: str
    log_path: str


class EmbeddingConfig(Strict):
    model: str
    max_tokens: PositiveInt
    window_tokens: PositiveInt


class RetrievalConfig(Strict):
    facts_threshold: UnitInterval
    ratio_threshold: UnitInterval
    top_k: PositiveInt


class SessionConfig(Strict):
    alternating_turns: PositiveInt
    parallel_closings: bool
    max_turn_tokens: PositiveInt


class ScoreWeights(Strict):
    rule: UnitInterval
    llm: UnitInterval


class ThemisLocalConfig(Strict):
    retry_cap: PositiveInt
    extraction_min_confidence: UnitInterval
    repetition_hard_threshold: UnitInterval
    score_weights: ScoreWeights
    penalty_cap: UnitInterval

    @model_validator(mode="after")
    def _weights_sum(self) -> ThemisLocalConfig:
        if not math.isclose(self.score_weights.rule + self.score_weights.llm, 1):
            raise ValueError("themis_local.score_weights must sum to 1")
        return self


class JudgingWeights(Strict):
    accuracy: UnitInterval
    consistency: UnitInterval
    rebuttal: UnitInterval
    grounding: UnitInterval


class JudgingConfig(Strict):
    weights: JudgingWeights
    order_swap_max_gap: UnitInterval
    tie_margin: UnitInterval

    @model_validator(mode="after")
    def _weights_sum(self) -> JudgingConfig:
        w = self.weights
        if not math.isclose(w.accuracy + w.consistency + w.rebuttal + w.grounding, 1):
            raise ValueError("judging.weights must sum to 1")
        return self


class MemoryConfig(Strict):
    pinned_token_budget: PositiveInt
    pinned_k: PositiveInt
    decay_lambda: UnitInterval
    retire_below_confidence: UnitInterval
    dedup_embedding_threshold: UnitInterval


class SplitsConfig(Strict):
    test_count: PositiveInt
    validation_count: PositiveInt


class AppConfig(Strict):
    version: str
    providers: dict[str, ProviderConfig]
    models: ModelsConfig
    prompts: PromptsConfig
    llm: LLMConfig
    embedding: EmbeddingConfig
    retrieval: RetrievalConfig
    session: SessionConfig
    themis_local: ThemisLocalConfig
    judging: JudgingConfig
    memory: MemoryConfig
    splits: SplitsConfig
    seed: int

    @model_validator(mode="after")
    def _providers_exist(self) -> AppConfig:
        for role, model in self.models.by_role().items():
            if model.provider not in self.providers:
                raise ValueError(f"models.{role}.provider '{model.provider}' is not defined under providers")
        return self
