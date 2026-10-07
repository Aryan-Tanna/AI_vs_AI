"""Law DB record (DATA_FORMATS §1). Frozen format: validated as documented, never reshaped."""

from __future__ import annotations

import hashlib
import json
from typing import Any

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


LIST_FIELDS = ("applicant_eligibility", "mandatory_prerequisites", "statutory_bars", "saving_exceptions")
SCALAR_FIELDS = ("financial_threshold", "adjudication_window_days", "rectification_window_days")


def checklist_item(record: LawRecord, field: str, index: int | None) -> Any:
    """The Law DB item a predicate encodes (DATA_FORMATS §4 `field`, `item_index`).

    Raises KeyError for an unknown field and IndexError for a missing list item.
    """
    if field in LIST_FIELDS:
        if index is None:
            raise IndexError(f"{field} is a list; item_index is required")
        items: list[str] = getattr(record.diagnostic_checklist, field)
        if not 0 <= index < len(items):
            raise IndexError(f"no item {index} in {field} (it has {len(items)})")
        return items[index]
    if index is not None:
        raise IndexError(f"{field} is not a list; item_index must be null")
    if field == "financial_threshold":
        return record.diagnostic_checklist.financial_threshold.to_document()
    if field in SCALAR_FIELDS:
        return getattr(record.procedural_timelines, field)
    raise KeyError(f"{field!r} is not a diagnostic_checklist or procedural_timelines field")


def item_hash(item: Any) -> str:
    """sha256 of a Law DB item (DATA_FORMATS §4 `item_hash`); a mismatch marks its predicate STALE."""
    canonical = json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def locate_item(record: LawRecord, field: str, index: int | None, wanted_hash: str) -> int | str | None:
    """Where the item with this hash is now: its list index, None for a scalar field, or "MISSING"."""
    if field in LIST_FIELDS:
        items: list[str] = getattr(record.diagnostic_checklist, field)
        for i, item in enumerate(items):
            if item_hash(item) == wanted_hash:
                return i
        return "MISSING"
    try:
        return None if item_hash(checklist_item(record, field, index)) == wanted_hash else "MISSING"
    except (KeyError, IndexError):
        return "MISSING"
