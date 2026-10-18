"""Hearing metrics computed in code after the verdict (D-137): report-only, never shown to agents, never a gate."""

from __future__ import annotations

from pydantic import Field

from lexarena.schemas.base import NonEmptyStr, Side, StoredModel


class SideMetrics(StoredModel):
    turns: int = Field(ge=0)
    issue_coverage: float | None  # share of framed issues this side addressed in at least one published turn
    rebuttal_depth: float | None  # THEMIS-GLOBAL: share of the opponent's points answered
    consistency: float | None  # THEMIS-GLOBAL: 1 - contradictions / tracked claims
    hard_errors: int = Field(ge=0)  # over every attempt
    retries: int = Field(ge=0)  # attempts beyond the first
    first_try_rate: float | None  # share of turns published on the first attempt
    flagged_turns: int = Field(ge=0)
    citation_tiers: dict[str, int]  # VERIFIED / REFERENCED / UNVERIFIABLE counts over assessed claims
    mean_repetition: (
        float | None
    )  # mean, over turns after the first, of the best similarity to this side's earlier turns
    max_repetition: float | None
    prerequisite_warnings: int = Field(ge=0)


class BenchMetrics(StoredModel):
    judges: int = Field(ge=0)
    abstentions: int = Field(ge=0)
    opinions: int = Field(ge=0)  # valid opinions
    order_flips: int = Field(ge=0)  # judges whose two orders gave different overall results
    issue_order_flips: int = Field(ge=0)  # (judge, issue) pairs decided differently in the two orders
    first_presented_wins: int = Field(ge=0)  # valid opinions whose result is the side presented first


class ReasoningAlignment(StoredModel):
    """The bench's governing law against the law the real court relied on (sealed record, after the verdict)."""

    real_statutes: list[NonEmptyStr]
    bench_statutes: list[NonEmptyStr]
    statute_precision: float | None
    statute_recall: float | None
    real_precedents: list[NonEmptyStr]  # precedents the court FOLLOWED or APPLIED, by precedent_id
    bench_precedents: list[NonEmptyStr]
    precedent_precision: float | None
    precedent_recall: float | None


class HearingMetrics(StoredModel):
    session_id: NonEmptyStr
    case_id: NonEmptyStr
    sides: dict[Side, SideMetrics]
    bench: BenchMetrics
    reasoning: ReasoningAlignment
