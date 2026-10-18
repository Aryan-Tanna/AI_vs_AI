"""Pydantic models for config/config.vN.yaml (DATA_FORMATS §6).

Every field is required: values live in the versioned YAML, never in code (non-negotiable 4).
Validators enforce invariants from CLAUDE.md and SPEC I3-7, not tuning choices.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lexarena.schemas.base import NonEmptyStr

UnitInterval = Annotated[float, Field(ge=0, le=1)]
PositiveInt = Annotated[int, Field(gt=0)]
PositiveFloat = Annotated[float, Field(gt=0)]
EnvVarName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]


HANDOFF_ROLES = ("clerk_primary", "clerk_extractor")  # D-127: the clerk roles a Claude Code agent may answer


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


class HandoffProviderConfig(Strict):
    """A Claude Code agent answering through files (D-127): pilot clerk only, never a session role."""

    kind: Literal["handoff"]
    exchange_dir: NonEmptyStr  # relative to the repo root; git-ignored (clerk prompts carry real names)


ProviderConfig = Annotated[
    OpenAICompatProviderConfig | GeminiProviderConfig | HandoffProviderConfig, Field(discriminator="kind")
]


class ProviderRouting(Strict):
    """Pins the upstream host on a routing gateway (OpenRouter's `provider` field). Hosts of one model differ in
    precision and in which parameters they honour, so both lawyers must be served by the same pinned build."""

    order: Annotated[list[str], Field(min_length=1)]
    allow_fallbacks: bool
    require_parameters: bool
    quantizations: list[str] | None


class ModelConfig(Strict):
    provider: str
    family: str
    name: str
    temperature: Annotated[float, Field(ge=0)]
    max_output_tokens: PositiveInt
    # Reasoning models only (sent as `reasoning_effort`); null for every other model (D-081).
    reasoning_effort: Literal["low", "medium", "high"] | None
    # false turns a reasoning model's hidden reasoning off (OpenRouter `reasoning.enabled`), for mechanical calls only
    # (D-102). Unset (null) sends nothing, so the cache keys of every model that does not use it are unchanged.
    reasoning_enabled: bool | None
    api_key_env: EnvVarName
    # Spare free keys, tried in order when a key's quota is spent (HTTP 429 with no short wait), D-118. Empty for paid
    # routes. Never part of the cache key: which key served a call cannot change the answer.
    fallback_key_envs: tuple[EnvVarName, ...]
    # Other models on the same provider, tried in order when this one is still overloaded (HTTP 503) after its retries
    # (D-123). Each answer is cached and logged under the model that gave it, and passes the same checks.
    fallback_models: tuple[NonEmptyStr, ...]
    # Gateway host pinning; omitted (null) for direct providers, so their cache keys are unchanged.
    routing: ProviderRouting | None


class ModelsConfig(Strict):
    lawyer: ModelConfig
    verifier: ModelConfig
    # THEMIS-LOCAL layer-1 checklist extraction, a mechanical mirror of the argument: same family rules as the verifier,
    # reasoning off because the call needs none (D-102). Judgement calls (layer-2 review, entailment) stay on verifier.
    extractor: ModelConfig
    # THEMIS layer 1 on the judges' stated law: a judge's opinion is longer than a lawyer's turn (D-092).
    judge_checker: ModelConfig
    judge: ModelConfig
    auditor: ModelConfig
    # Names for pseudonyms and routing (agent view vs sealed): the spoiler-hiding steps, on a free key (D-121).
    clerk_primary: ModelConfig
    # Record facts, agent view, ground truth and the agent-view repair (D-121).
    clerk_extractor: ModelConfig
    clerk_secondary: ModelConfig
    # D-127: pilot only. `lexarena clerk run --handoff` puts it in place of clerk_primary and clerk_extractor when the
    # free model is down; clerk_secondary still checks its facts.
    clerk_handoff: ModelConfig
    reflection: ModelConfig
    # Step 3: two independent extractors draft side-collection items for human review (D-041).
    drafter_primary: ModelConfig
    drafter_secondary: ModelConfig

    def by_role(self) -> dict[str, ModelConfig]:
        return {name: getattr(self, name) for name in type(self).model_fields}

    @model_validator(mode="after")
    def _invariants(self) -> ModelsConfig:
        # SPEC I3-7: THEMIS (layer 2 and global) must not share the lawyers' model family.
        for role in ("verifier", "extractor", "judge_checker", "auditor"):
            if getattr(self, role).family == self.lawyer.family:
                raise ValueError(f"models.{role}.family must differ from models.lawyer.family (SPEC I3-7)")
        # Two-model agreement in the clerk (ARCHITECTURE §3) needs independent families.
        if self.clerk_primary.family == self.clerk_secondary.family:
            raise ValueError("models.clerk_primary.family must differ from models.clerk_secondary.family")
        if self.clerk_extractor.family == self.clerk_secondary.family:
            raise ValueError("models.clerk_extractor.family must differ from models.clerk_secondary.family")
        if self.clerk_handoff.family in (self.clerk_secondary.family, self.lawyer.family):
            raise ValueError("models.clerk_handoff.family must differ from models.clerk_secondary and models.lawyer")
        if self.drafter_primary.family == self.drafter_secondary.family:
            raise ValueError("models.drafter_primary.family must differ from models.drafter_secondary.family")
        # CLAUDE.md: verifiers and extractors run at temperature 0.
        for role in (
            "verifier",
            "extractor",
            "judge_checker",
            "auditor",
            "clerk_primary",
            "clerk_extractor",
            "clerk_secondary",
            "clerk_handoff",
            "drafter_primary",
            "drafter_secondary",
        ):
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
    clerk_entities: PromptRef
    clerk_route: PromptRef
    clerk_record_facts: PromptRef
    clerk_agent_view: PromptRef
    clerk_ground_truth: PromptRef
    clerk_entailment: PromptRef
    clerk_probe: PromptRef
    clerk_agent_view_repair: PromptRef
    themis_extract: PromptRef
    themis_layer2: PromptRef
    themis_fidelity_confirm: PromptRef  # D-105: confirm before a record-fidelity rejection
    themis_entailment: PromptRef
    themis_global_audit: PromptRef
    reflection_lessons: PromptRef
    reflection_compare: PromptRef
    judge_decide: PromptRef
    judge_revise: PromptRef
    single_llm: PromptRef
    agent_rules: PromptRef
    agent_role: PromptRef
    agent_plan: PromptRef
    agent_notes: PromptRef
    agent_turn: PromptRef
    hearing_era: PromptRef  # D-144: the hearing year, for lawyers and the bench
    agent_turn_opening: PromptRef  # D-135: one instruction per turn type
    agent_turn_rebuttal: PromptRef
    agent_turn_closing: PromptRef
    agent_repetition_note: PromptRef
    judge_personas: dict[Literal["TEXTUALIST", "PURPOSIVIST", "PROCEDURALIST"], PromptRef]

    @model_validator(mode="after")
    def _every_persona(self) -> PromptsConfig:
        missing = {"TEXTUALIST", "PURPOSIVIST", "PROCEDURALIST"} - set(self.judge_personas)
        if missing:
            raise ValueError(f"prompts.judge_personas lacks {sorted(missing)} (INTENT: three personas)")
        return self


class VocabularyConfig(Strict):
    """Names shared across components, so a label one writes is a label another can read (D-041).

    `case_date_labels`: the key_dates labels the clerk may emit and overlay rows may key on; DECISION is
    the simulation_date. `overlay_parameters`: the temporal_overlay parameter names consumers understand.
    """

    case_date_labels: list[Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]]
    overlay_parameters: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]]
    party_statuses: list[Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]] = Field(min_length=1)

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
    # D-110: the owner's session trace (answers, reasoning, THEMIS checks, opinions) for the courtroom viewer.
    trace_enabled: bool
    trace_dir: str
    chars_per_token: PositiveFloat  # D-077: budget estimate where the model has no local tokenizer


class EmbeddingConfig(Strict):
    model: str
    max_tokens: PositiveInt
    window_tokens: PositiveInt
    batch_size: PositiveInt
    cache_dir: str
    query_instruction: str  # prefixed to asymmetric (proposition -> ratio) queries only [SPEC B5]


class RerankerConfig(Strict):
    enabled: bool
    model: str


class RetrievalConfig(Strict):
    facts_threshold: UnitInterval
    ratio_threshold: UnitInterval
    top_k: PositiveInt
    candidate_pool: PositiveInt
    card_text_tokens: PositiveInt
    reranker: RerankerConfig

    @model_validator(mode="after")
    def _pool_covers_top_k(self) -> RetrievalConfig:
        if self.candidate_pool < self.top_k:
            raise ValueError("retrieval.candidate_pool must be at least retrieval.top_k")
        return self


class SessionConfig(Strict):
    alternating_turns: PositiveInt
    parallel_closings: bool
    max_turn_tokens: PositiveInt
    lawyer_input_tokens: PositiveInt  # D-079: per-call budget; the transcript condenses to fit
    research_queries: PositiveInt  # D-053: strategy-phase searches per side
    # D-112: each side's knowledge-base lookups, answered before its next submission; the same caps for both sides.
    lookups_per_turn: int = Field(ge=0)
    lookup_tokens: PositiveInt  # all answers to one submission's lookups share this budget
    lookup_lessons_k: PositiveInt  # lessons returned by one LESSONS lookup
    words_per_token: PositiveFloat


class ScoreWeights(Strict):
    rule: UnitInterval
    llm: UnitInterval


class UnitWord(Strict):
    word: NonEmptyStr
    value: PositiveInt


class DateReading(Strict):
    key: NonEmptyStr
    alternative: NonEmptyStr


class LimitationConfig(Strict):
    period_parameter: NonEmptyStr
    excluded_parameter: NonEmptyStr
    minimum_balance_parameter: NonEmptyStr
    default_date_label: NonEmptyStr
    filing_date_label: NonEmptyStr


class ThemisLocalConfig(Strict):
    retry_cap: PositiveInt
    extraction_min_confidence: UnitInterval
    repetition_hard_threshold: UnitInterval
    repetition_hard_error: bool  # D-105: false makes repetition a warning on every turn
    confirm_fidelity_rejections: bool  # D-105: a second narrow call must agree before ERR_FACT_NOT_IN_RECORD
    repetition_warn_threshold: UnitInterval
    score_weights: ScoreWeights
    penalty_cap: UnitInterval
    threshold_overlay_parameter: NonEmptyStr
    threshold_currency: NonEmptyStr
    amount_unit_words: list[UnitWord]
    threshold_date_readings: list[DateReading]
    limitation: LimitationConfig

    @model_validator(mode="after")
    def _repetition_order(self) -> ThemisLocalConfig:
        if self.repetition_warn_threshold > self.repetition_hard_threshold:
            raise ValueError("themis_local.repetition_warn_threshold must not exceed repetition_hard_threshold")
        return self

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
    tie_break: Literal["ADVOCACY_SCORE", "NONE"]  # D-048; D-105: NONE leaves an even split UNSTABLE
    abstain_on_order_swap_disagreement: bool  # D-051
    min_deciding_judges: int  # D-051: fewer deciding judges -> UNSTABLE verdict, reported apart, never decided
    check_reasons_with_layer1: bool  # D-071: THEMIS layer 1 checks the law each opinion states
    orders_per_persona: Literal[1, 2]  # literal-ok: the two allowed order counts (D-093), not a tuning value
    show_audit_notes: bool  # D-078: the auditor's map of the transcript, never its scores
    show_audit_contradictions: bool  # D-105: unconfirmed self-contradictions are left out of the judges' notes
    lookups_per_opinion: int = Field(ge=0)  # D-112: knowledge-base lookups a judge may ask for; 0 turns them off
    max_order_swap_disagreement_rate: UnitInterval  # report limit (D-024, D-071)
    persona_role_max_win_rate: UnitInterval  # SPEC E1 persona bias flag
    persona_role_min_cases: PositiveInt  # SPEC E1

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
    require_human_reviewed_case: bool  # D-094: no lessons from a case the owner has not reviewed
    accept_claude_triage: bool  # D-114: your override for the pilot: a Claude-triaged case may teach lessons too
    pinned_token_budget: PositiveInt
    pinned_k: PositiveInt
    explore_k: int = Field(ge=0)  # D-111: lessons drawn at random from the rest of the eligible pool, same rule for all
    decay_lambda: UnitInterval
    retire_below_confidence: UnitInterval
    dedup_embedding_threshold: UnitInterval
    initial_confidence: UnitInterval
    confidence_step: UnitInterval
    max_lessons_per_case: PositiveInt
    base_rate_markers: list[NonEmptyStr]
    # D-139: lessons are strategy and method, never a statement of the law; a lesson with any of these is rejected.
    legal_conclusion_markers: list[NonEmptyStr]
    # D-140: words that carry a figure without a digit ("one crore"); a lesson never carries a figure.
    figure_words: list[NonEmptyStr]
    # D-139: provisions of these Law DB jurisdiction types (the appeal provisions) never key a lesson: they attach to
    # every appeal, so a lesson keyed on them would be pinned into unrelated cases.
    unkeyed_jurisdiction_types: list[NonEmptyStr]
    # D-139: lawyer lessons transfer within a family of party statuses (same rule for both sides); a status in no
    # family matches only itself.
    party_status_families: list[list[NonEmptyStr]]

    def family_of(self) -> dict[str, str]:
        """Party status -> its family's first status (the family's name)."""
        return {status: family[0] for family in self.party_status_families for status in family}


class EvaluationConfig(Strict):
    single_llm_role: NonEmptyStr  # D-072: a models.<role>; checked against the models below
    bootstrap_resamples: PositiveInt
    confidence_level: Annotated[float, Field(gt=0, lt=1)]


class QuotaLimit(Strict):
    model: NonEmptyStr
    api_key_env: EnvVarName
    requests_per_window: PositiveInt
    tokens_per_window: PositiveInt | None


class RoleRequests(Strict):
    role: NonEmptyStr
    requests: PositiveInt


class StageRequests(Strict):
    SESSION: list[RoleRequests]
    BASELINE: list[RoleRequests]
    EVALUATE: list[RoleRequests]
    REFLECT: list[RoleRequests]

    def for_stage(self, stage: str) -> dict[str, int]:
        return {r.role: r.requests for r in getattr(self, stage)}


class ModelPrice(Strict):
    """What one (provider, model) pair costs, in US dollars per million tokens. A free key is a row of zeros."""

    provider: NonEmptyStr
    model: NonEmptyStr
    input_usd_per_m: Annotated[float, Field(ge=0)]
    output_usd_per_m: Annotated[float, Field(ge=0)]


class StageCost(Strict):
    """The most one stage is expected to cost, in US dollars (checked before it starts, D-109)."""

    SESSION: Annotated[float, Field(ge=0)]
    BASELINE: Annotated[float, Field(ge=0)]
    EVALUATE: Annotated[float, Field(ge=0)]
    REFLECT: Annotated[float, Field(ge=0)]


class RunnerConfig(Strict):
    runs_dir: NonEmptyStr
    allowed_splits: list[Literal["DEV", "TRAIN", "VALIDATION", "TEST"]] = Field(min_length=1)
    stage_timeout_s: PositiveFloat
    quota_window_hours: PositiveFloat
    ablations: list[NonEmptyStr]
    quotas: list[QuotaLimit]
    stage_requests: StageRequests
    # Money (D-109): a run pauses before a stage when what it has spent plus that stage's expected cost would pass the
    # cap. Spend is priced from the call log by (provider, model); a paid call with no price row pauses the run.
    spend_cap_usd: PositiveFloat
    # D-109: when set, spend counts from this moment for every run, so a pilot run in batches shares one cap; when null,
    # each run counts from when it was planned.
    spend_counted_from: datetime | None
    stage_cost_usd: StageCost
    prices: list[ModelPrice] = Field(min_length=1)


class SplitsConfig(Strict):
    test_count: PositiveInt
    validation_count: PositiveInt


class ClerkConfig(Strict):
    version: NonEmptyStr
    furniture_min_page_share: UnitInterval
    body_start_headings: list[NonEmptyStr] = Field(min_length=1)
    max_paragraph_number_jump: PositiveInt
    max_first_paragraph_number: PositiveInt
    min_paragraphs_per_page: float = Field(gt=0)
    running_text_min_chars: PositiveInt
    entailment_batch_chars: PositiveInt
    repair_rounds: int = Field(ge=0)
    repair_max_output_tokens: PositiveInt  # D-109: the repair step's own output cap, below the extractor's
    leakage_ngram: PositiveInt
    grounds_max_ratio: float = Field(gt=1)
    presumptions: list[NonEmptyStr] = Field(min_length=1)
    evaluative_words: list[NonEmptyStr] = Field(min_length=1)
    route_chars_per_paragraph: PositiveInt
    generic_name_words: list[NonEmptyStr]
    court_voice_markers: list[NonEmptyStr] = Field(min_length=1)


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
    evaluation: EvaluationConfig
    runner: RunnerConfig
    memory: MemoryConfig
    splits: SplitsConfig
    vocabulary: VocabularyConfig
    drafting: DraftingConfig
    clerk: ClerkConfig
    seed: int

    def with_clerk_handoff(self, roles: tuple[str, ...] = HANDOFF_ROLES) -> AppConfig:
        """These clerk roles answered by the handoff model (D-127); every other role unchanged. One role only keeps the
        other's cached answers, e.g. names and routing from Gemini with only the extraction handed off (D-131)."""
        if not roles or set(roles) - set(HANDOFF_ROLES):
            raise ValueError(f"handoff roles must be among {HANDOFF_ROLES}")
        h = self.models.clerk_handoff
        models = self.models.model_copy(update=dict.fromkeys(roles, h))
        return self.model_copy(update={"models": models})

    @model_validator(mode="after")
    def _turn_fits_the_lawyer(self) -> AppConfig:
        # A submission, its claims list and the model's reasoning share the lawyer's output cap (D-082).
        if self.session.max_turn_tokens >= self.models.lawyer.max_output_tokens:
            raise ValueError("session.max_turn_tokens must leave room in models.lawyer.max_output_tokens")
        return self

    @model_validator(mode="after")
    def _families_are_known_and_disjoint(self) -> AppConfig:
        seen: list[str] = [s for family in self.memory.party_status_families for s in family]
        unknown = sorted(set(seen) - set(self.vocabulary.party_statuses))
        twice = sorted({s for s in seen if seen.count(s) > 1})
        if unknown or twice:
            raise ValueError(f"memory.party_status_families: unknown statuses {unknown}, in two families {twice}")
        return self

    @model_validator(mode="after")
    def _providers_exist(self) -> AppConfig:
        for role, model in self.models.by_role().items():
            if model.provider not in self.providers:
                raise ValueError(f"models.{role}.provider '{model.provider}' is not defined under providers")
            if model.routing is not None and self.providers[model.provider].kind != "openai_compatible":
                raise ValueError(f"models.{role}.routing needs an openai_compatible provider")
        roles = set(self.models.by_role())
        sr = self.runner.stage_requests
        named = {r.role for stage in type(sr).model_fields for r in getattr(sr, stage)}
        unknown = sorted(named - roles)
        if unknown:
            raise ValueError(f"runner.stage_requests names unknown model roles {unknown}")
        if self.evaluation.single_llm_role not in self.models.by_role():
            raise ValueError(f"evaluation.single_llm_role '{self.evaluation.single_llm_role}' is not a model role")
        return self
