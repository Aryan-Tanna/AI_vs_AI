"""Law DB record (DATA_FORMATS §1). Frozen format: validated as documented, never reshaped."""

from __future__ import annotations

from pydantic import Field, model_validator

from lexarena.schemas.base import FrozenFormatModel


class FinancialThreshold(FrozenFormatModel):
    minimum_amount: int | float | None
    currency: str | None


class DiagnosticChecklist(FrozenFormatModel):
    applicant_eligibility: list[str]
    financial_threshold: FinancialThreshold
    mandatory_prerequisites: list[str]
    statutory_bars: list[str]
    saving_exceptions: list[str]


class ProceduralTimelines(FrozenFormatModel):
    adjudication_window_days: int | None
    rectification_window_days: int | None


class LawRecord(FrozenFormatModel):
    id: str = Field(alias="_id", min_length=1)
    statute_id: str = Field(min_length=1)
    act_name: str
    section_number: str
    section_title: str
    jurisdiction_type: str
    forum_level: str
    statutory_summary: str
    core_judicial_inquiry: str
    intersecting_statute_ids: list[str]
    diagnostic_checklist: DiagnosticChecklist
    procedural_timelines: ProceduralTimelines
    audit_error_codes: list[str]

    @model_validator(mode="after")
    def _id_matches_statute_id(self) -> LawRecord:
        if self.id != self.statute_id:
            raise ValueError(f"_id {self.id!r} must equal statute_id {self.statute_id!r} (DATA_FORMATS §1)")
        return self
