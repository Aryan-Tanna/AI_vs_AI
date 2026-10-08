"""What the THEMIS-LOCAL extractor model returns (SPEC D1; D-062).

The stored form is `ExtractedChecklist` (transcript.py). This model-facing form avoids what strict JSON-schema modes
refuse (free-form maps, optional keys): readings are a list of pairs and every field is present.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from lexarena.schemas.base import NonEmptyStr, StoredModel
from lexarena.schemas.transcript import ClaimedChecklist, ClaimedTimelines, ExtractedChecklist, Stance


class ChosenReading(StoredModel):
    parameter: NonEmptyStr
    option: NonEmptyStr


class ChecklistDraft(StoredModel):
    statute_id: NonEmptyStr
    stance: Stance
    asserts_threshold_met: bool | None
    threshold_amount_id: str | None
    chosen_readings: list[ChosenReading]
    asserts_within_limitation: bool | None
    acknowledgment_dates: list[date]
    diagnostic_checklist: ClaimedChecklist
    procedural_timelines: ClaimedTimelines
    # The argument's own words behind each claim that can cause a hard error (SPEC D1 point 4, D-066). Code checks
    # each is verbatim in the argument and, for a number, that the number is in it; otherwise the claim is dropped.
    minimum_amount_quote: str | None
    threshold_met_quote: str | None
    adjudication_window_quote: str | None
    rectification_window_quote: str | None

    def to_checklist(self, valid_amount_ids: set[str]) -> ExtractedChecklist:
        return ExtractedChecklist(
            statute_id=self.statute_id,
            stance=self.stance,
            asserts_threshold_met=self.asserts_threshold_met,
            threshold_amount_id=self.threshold_amount_id if self.threshold_amount_id in valid_amount_ids else None,
            chosen_readings={r.parameter: r.option for r in self.chosen_readings},
            asserts_within_limitation=self.asserts_within_limitation,
            acknowledgment_dates=self.acknowledgment_dates,
            diagnostic_checklist=self.diagnostic_checklist,
            procedural_timelines=self.procedural_timelines,
        )


class ArgumentExtraction(StoredModel):
    checklists: list[ChecklistDraft]


# ---------------------------------------------------------------- layer 2 (SPEC D4, D5, A2; D-075)


class FidelityIssue(StoredModel):
    kind: Literal["NOT_IN_RECORD", "EXHIBIT_CONTENT_FABRICATED"]
    quote: str  # the argument's own words, copied exactly; code checks they are in the argument
    record_ids: list[str]  # the items the words claim to describe, or the nearest items they contradict
    explanation: str
    confidence: float


class OpponentPoint(StoredModel):
    point: str
    addressed: bool


class Layer2Review(StoredModel):
    """One verifier call per draft: record fidelity (A2) and responsiveness to the opponent's last turn (D5)."""

    fidelity_issues: list[FidelityIssue]
    opponent_points: list[OpponentPoint]


class EntailmentVerdict(StoredModel):
    claim_id: str
    precedent_uid: str
    verdict: Literal["SUPPORTS", "CONTRADICTS", "NOT_ADDRESSED"]
    ratio_quote: str  # for CONTRADICTS: the ratio's own words that contradict the claim, copied exactly


class EntailmentBatch(StoredModel):
    verdicts: list[EntailmentVerdict]
