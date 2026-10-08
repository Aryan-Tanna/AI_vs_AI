"""Transcript turns (SPEC H3), stored in two collections (D-035):

- `transcript_turns` holds `PublishedTurn`: what both lawyers, THEMIS and the judges may read
  (text, the claims the advocate made with the IDs they rest on, and FLAGGED codes).
- `turn_private` holds `PrivateTurnData`: THEMIS-LOCAL attempts, warnings, scores, citation tiers,
  entailment results and extracted checklists. SPEC I1 and E1 give these to the owning side's reflection
  only; keeping them in a separate collection means no projection mistake can show them to the opponent
  or the judges.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field, model_validator

from lexarena.schemas.base import NonEmptyStr, Side, StoredModel, UnitScore, UpperCode
from lexarena.schemas.case import AmountId, CaseId, IssueId
from lexarena.schemas.codes import HardErrorCode

Stance = Literal["ASSERT_CLAIM", "INVOKE_BAR", "INVOKE_EXCEPTION"]


def turn_document_id(session_id: str, turn: int) -> str:
    return f"{session_id}_T{turn:02d}"


# ---------------------------------------------------------------- public


class PublicClaim(StoredModel):
    claim_id: NonEmptyStr
    type: Literal["FACT", "LAW"]
    text: NonEmptyStr
    record_ids: list[NonEmptyStr]
    statute_id: NonEmptyStr | None
    precedent_ids: list[NonEmptyStr]


class VisibleFlag(StoredModel):
    """A hard error left after the retry cap (SPEC D8 FLAGGED): shown to the opponent and the judges."""

    code: HardErrorCode
    claim_ids: list[NonEmptyStr]
    record_ids: list[NonEmptyStr]


class PublishedTurn(StoredModel):
    id: NonEmptyStr = Field(alias="_id")
    case_id: CaseId
    session_id: NonEmptyStr
    turn: int = Field(ge=1)
    speaker: Side
    turn_type: UpperCode
    issues_addressed: list[IssueId]
    published_text: NonEmptyStr
    claims: list[PublicClaim]
    visible_flags: list[VisibleFlag]
    created_at: datetime

    @model_validator(mode="after")
    def _id_shape(self) -> PublishedTurn:
        if self.id != turn_document_id(self.session_id, self.turn):
            raise ValueError(f"turn _id must be {turn_document_id(self.session_id, self.turn)!r}")
        return self


# ---------------------------------------------------------------- private


class ClaimedItem(StoredModel):
    law_index: int | None = Field(ge=0)
    quote: str
    confidence: UnitScore


class ClaimedThreshold(StoredModel):
    minimum_amount: float | None  # one number type: Groq's strict JSON mode refuses an int|float union (D-062)
    currency: str | None


class ClaimedChecklist(StoredModel):
    applicant_eligibility: list[ClaimedItem]
    financial_threshold: ClaimedThreshold
    mandatory_prerequisites: list[ClaimedItem]
    statutory_bars: list[ClaimedItem]
    saving_exceptions: list[ClaimedItem]


class ClaimedTimelines(StoredModel):
    adjudication_window_days: int | None
    rectification_window_days: int | None


class ExtractedChecklist(StoredModel):
    """One per statute an argument relies on, mirroring the Law DB checklist keys (SPEC D1)."""

    statute_id: NonEmptyStr
    stance: Stance
    asserts_threshold_met: bool | None
    # The record amount the argument says meets (or misses) the threshold; None when it names none (D-062).
    threshold_amount_id: AmountId | None = None
    # The reading the argument chose for each open parameter of this statute's predicates (SPEC D2).
    chosen_readings: dict[str, str] = Field(default_factory=dict)
    # Limitation, when this checklist is for the limitation article: the argument's conclusion and the
    # acknowledgment dates it relies on (SPEC D3; D-063). Checked as a warning, never a hard error.
    asserts_within_limitation: bool | None = None
    acknowledgment_dates: list[date] = Field(default_factory=list)
    diagnostic_checklist: ClaimedChecklist
    procedural_timelines: ClaimedTimelines


class ThemisWarning(StoredModel):
    code: UpperCode
    field: str | None = None
    law_indices: list[int] | None = None
    quote: str | None = None
    detail: str | None = None


class ThemisLocalResult(StoredModel):
    outcome: Literal["PASS", "PASS_WITH_NOTES", "FLAGGED"]  # REVISE is never a final outcome (SPEC D8)
    attempts: int = Field(ge=1)
    hard_errors_by_attempt: list[list[HardErrorCode]]
    warnings: list[ThemisWarning]
    s_local: UnitScore

    @model_validator(mode="after")
    def _outcome_matches_errors(self) -> ThemisLocalResult:
        if len(self.hard_errors_by_attempt) != self.attempts:
            raise ValueError("hard_errors_by_attempt needs one entry per attempt")
        final_errors = self.hard_errors_by_attempt[-1]
        if (self.outcome == "FLAGGED") != bool(final_errors):
            raise ValueError("FLAGGED if and only if the published attempt still has hard errors")
        if self.outcome == "PASS" and self.warnings:
            raise ValueError("PASS has no warnings; use PASS_WITH_NOTES")
        if self.outcome == "PASS_WITH_NOTES" and not self.warnings:
            raise ValueError("PASS_WITH_NOTES needs at least one warning or UNMAPPED note")
        return self


class ClaimAssessment(StoredModel):
    claim_id: NonEmptyStr
    citation_tier: Literal["VERIFIED", "REFERENCED", "UNVERIFIABLE"] | None
    entailment: Literal["SUPPORTS", "CONTRADICTS", "NEUTRAL"] | None


class PrivateTurnData(StoredModel):
    id: NonEmptyStr = Field(alias="_id")
    case_id: CaseId
    session_id: NonEmptyStr
    turn: int = Field(ge=1)
    side: Side
    themis_local: ThemisLocalResult
    claim_assessments: list[ClaimAssessment]
    statute_checklists: list[ExtractedChecklist]

    @model_validator(mode="after")
    def _id_shape(self) -> PrivateTurnData:
        if self.id != turn_document_id(self.session_id, self.turn):
            raise ValueError(f"private turn _id must be {turn_document_id(self.session_id, self.turn)!r}")
        return self
