"""Shapes for drafting: what a model proposes, and the review file wrapped around it (D-041).

Model-facing proposals are deliberately plain (strings, no patterns or formats) so every provider's JSON
mode accepts them; everything is validated afterwards in code, and failures become blocking problems in the
review file rather than retries.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from lexarena.schemas.base import NonEmptyStr, StoredModel
from lexarena.schemas.predicate import PredicateEntry

ReviewStatus = Literal["DRAFT", "APPROVED", "REJECTED"]
Agreement = Literal["AGREED", "DISAGREED", "PRIMARY_ONLY", "SECONDARY_ONLY"]
CheckStatus = Literal["VERIFIED", "NOT_FOUND", "MISSING", "MATCHED", "NOT_MATCHED", "NOT_CHECKABLE", "OK", "FAILED"]


class _Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProposedOverlayRow(_Proposal):
    parameter: str
    value_kind: Literal["boolean", "number", "date_range", "text"]
    value_boolean: bool | None
    value_number: float | None
    value_from: str | None
    value_to: str | None
    value_text: str | None
    keyed_on: str
    effective_from: str | None
    effective_to: str | None
    source_text: str
    value_quote: str
    effective_from_quote: str | None
    effective_to_quote: str | None
    commencement_note: str | None


class OverlayProposal(_Proposal):
    rows: list[ProposedOverlayRow]
    no_rows_reason: str | None


class ProposedInput(_Proposal):
    name: str
    source: str


class ProposedOpenParameter(_Proposal):
    name: str
    options: list[str]
    note: str


class ProposedPredicate(_Proposal):
    field: str
    item_index: int | None
    kind: str
    inputs: list[ProposedInput]
    open_parameters: list[ProposedOpenParameter]
    expression_json: str
    error_code: str
    source_text: str


class PredicateProposal(_Proposal):
    predicates: list[ProposedPredicate]
    no_predicate_reason: str | None


class Check(StoredModel):
    name: str
    status: CheckStatus
    detail: str


class _Draft(StoredModel):
    draft_id: NonEmptyStr
    statute_id: NonEmptyStr
    source_id: NonEmptyStr
    source_text_sha256: str
    status: ReviewStatus
    decided_by: str | None
    decided_on: date | None
    decision_note: str | None
    agreement: Agreement
    conflicts_with: list[str]
    proposed_by: list[str]
    prompt_ref: NonEmptyStr  # e.g. drafting/overlay.v3: which instructions produced this draft
    checks: list[Check]
    blocking_problems: list[str]
    reviewer_must_judge: list[str]
    created_at: datetime


class OverlayDraft(_Draft):
    kind: Literal["temporal_overlay"]
    row: ProposedOverlayRow


class PredicateDraft(_Draft):
    kind: Literal["predicate_registry"]
    proposal: ProposedPredicate
    item_hash: str | None
    entry: PredicateEntry | None  # None when the proposal could not be built into a valid entry


Draft = Annotated[OverlayDraft | PredicateDraft, Field(discriminator="kind")]
