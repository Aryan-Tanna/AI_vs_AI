"""temporal_overlay rows (DATA_FORMATS §3): law that changes with dates. Only APPROVED rows load."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from lexarena.schemas.base import NonEmptyStr, StoredModel, UpperCode

ReviewStatus = Literal["DRAFT", "APPROVED", "RETIRED"]

# Names the code gives meaning to (D-039, D-042). Whether a provision exists is decided on the hearing date
# (DECISION = simulation_date); whether it reaches earlier facts is a separate, fact-keyed or open question.
IN_FORCE_PARAMETER = "section_in_force"
DECISION_LABEL = "DECISION"


class DateRange(StoredModel):
    from_: date = Field(alias="from")
    to: date

    @model_validator(mode="after")
    def _ordered(self) -> DateRange:
        if self.from_ > self.to:
            raise ValueError("date range 'from' is after 'to'")
        return self


class TemporalOverlayRow(StoredModel):
    overlay_id: NonEmptyStr
    statute_id: NonEmptyStr
    parameter: NonEmptyStr
    # bool first: smart-mode unions keep True/False as booleans rather than coercing them to numbers.
    value: bool | int | float | DateRange | str
    keyed_on: UpperCode
    effective_from: date | None
    effective_to: date | None
    source_ref: NonEmptyStr
    source_text: NonEmptyStr
    status: ReviewStatus
    approved_by: str | None
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def _consistent(self) -> TemporalOverlayRow:
        if self.effective_from and self.effective_to and self.effective_from > self.effective_to:
            raise ValueError("effective_from is after effective_to")
        if self.status == "APPROVED" and not self.approved_by:
            raise ValueError("an APPROVED row must name approved_by")
        if self.parameter == IN_FORCE_PARAMETER and self.keyed_on != DECISION_LABEL:
            raise ValueError(
                f"{IN_FORCE_PARAMETER} must key on {DECISION_LABEL} (D-042): it says whether the provision exists "
                "at the hearing; whether it reaches earlier facts belongs in another parameter or stays open"
            )
        return self
