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
    # Step 3: two independent extractors draft side-collection items for human review (D-041).
    drafter_primary: ModelConfig
    drafter_secondary: ModelConfig

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
        if self.drafter_primary.family == self.drafter_secondary.family:
            raise ValueError("models.drafter_primary.family must differ from models.drafter_secondary.family")
        # CLAUDE.md: verifiers and extractors run at temperature 0.
        for role in ("verifier", "auditor", "clerk_primary", "clerk_secondary", "drafter_primary", "drafter_secondary"):
            if getattr(self, role).temperature != 0:
                raise ValueError(f"models.{role}.temperature must be 0 (verifiers and extractors are deterministic)")
        return self


class PromptRef(Strict):
    id: str
    version: PositiveInt


class PromptsConfig(Strict):
    schema_repair: PromptRef
    smoke: PromptRef
    draft_overlay: PromptRef
    draft_predicate: PromptRef


class VocabularyConfig(Strict):
    """Names shared across components, so a label one writes is a label another can read (D-041).

    `case_date_labels`: the key_dates labels the clerk may emit and overlay rows may key on; DECISION is
    the simulation_date. `overlay_parameters`: the temporal_overlay parameter names consumers understand.
    """

    case_date_labels: list[Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]]
    overlay_parameters: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]]

    @model_validator(mode="after")
    def _required_names(self) -> VocabularyConfig:
        # Names the code gives meaning to (lexarena.storage.temporal); without them get_statute cannot work.
        if "DECISION" not in self.case_date_labels:
            raise ValueError("vocabulary.case_date_labels must include DECISION (the simulation_date)")
        if "section_in_force" not in self.overlay_parameters:
            raise ValueError("vocabulary.overlay_parameters must include section_in_force")
        return self


class DraftingConfig(Strict):
    excerpt_chars: PositiveInt
    max_excerpts: PositiveInt


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
    batch_size: PositiveInt
    cache_dir: str


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
    verdict_rule: Literal["BENCH_MAJORITY"]  # D-048
    tie_break: Literal["ADVOCACY_SCORE"]  # D-048: the score decides only an equal split of deciding judges
    abstain_on_order_swap_disagreement: bool  # D-051
    min_deciding_judges: int  # D-051: fewer deciding judges -> UNSTABLE verdict, reported apart, never decided

    @model_validator(mode="after")
    def _no_lone_judge(self) -> JudgingConfig:
        if self.min_deciding_judges <= 1:
            raise ValueError("judging.min_deciding_judges must be more than one: a lone judge never decides a case")
        return self

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
    vocabulary: VocabularyConfig
    drafting: DraftingConfig
    seed: int

    @model_validator(mode="after")
    def _providers_exist(self) -> AppConfig:
        for role, model in self.models.by_role().items():
            if model.provider not in self.providers:
                raise ValueError(f"models.{role}.provider '{model.provider}' is not defined under providers")
        return self
