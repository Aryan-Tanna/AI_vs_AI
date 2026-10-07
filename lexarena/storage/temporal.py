"""Which version of a provision applies to a case (SPEC C2, I3-3; DATA_FORMATS §3).

`resolve_statute` takes a Law DB record, its overlay rows and the case's dates, and returns what a
reader may see:

- Only APPROVED rows for this statute count (non-negotiable 8). Each row is evaluated on the case date
  named by its `keyed_on` label; a label the case does not have is reported, never guessed.
- `section_in_force` rows decide visibility. If any applicable row says the section is not in force on
  its date, or in-force rows exist but none covers the date, the section is hidden (None), exactly like
  an unknown ID, so a hidden section's existence does not leak. With no applicable in-force rows the
  section is shown as UNVERIFIED (D-022: missing approvals never block).
- Every other parameter is reported for the date it applies to; the Law DB record itself is returned
  unchanged, so readers see both the stored value and the dated one.
- Two applicable rows for one parameter on the same date is a data error, raised rather than resolved.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection
from datetime import date
from typing import TYPE_CHECKING, Literal

from lexarena.schemas.base import StoredModel
from lexarena.schemas.law import LawRecord
from lexarena.schemas.overlay import DECISION_LABEL, IN_FORCE_PARAMETER, DateRange, TemporalOverlayRow

if TYPE_CHECKING:
    from lexarena.schemas.case import Case


class OverlayConflictError(ValueError):
    """Approved overlay rows that contradict each other for one date."""


class AsOf(StoredModel):
    """The case dates overlay rows key on: `key_dates` labels plus DECISION (the simulation_date)."""

    key_dates: dict[str, date]

    @classmethod
    def for_case(cls, case: Case) -> AsOf:
        meta = case.agent_view.metadata
        dates = {kd.label: kd.date for kd in meta.key_dates}
        return cls(key_dates={**dates, DECISION_LABEL: meta.simulation_date})


class AppliedOverlay(StoredModel):
    """No date here on purpose: a row keyed on DECISION would otherwise hand the simulation_date to every
    session role (D-035). Readers know their own key dates; the label says which one was used."""

    overlay_id: str
    parameter: str
    value: bool | int | float | DateRange | str
    keyed_on: str


class UnresolvedOverlay(StoredModel):
    overlay_id: str
    parameter: str
    keyed_on: str
    reason: str


class StatuteView(StoredModel):
    statute_id: str
    record: LawRecord
    in_force: Literal["CONFIRMED", "UNVERIFIED"]
    applied: list[AppliedOverlay]
    unresolved: list[UnresolvedOverlay]
    # intersecting_statute_ids that exist in the Law DB, in record order (D-040). Whether each one is in force
    # on the case dates is decided when it is itself fetched with get_statute.
    related_ids: list[str]


def covers(row: TemporalOverlayRow, day: date) -> bool:
    return (row.effective_from is None or row.effective_from <= day) and (
        row.effective_to is None or day <= row.effective_to
    )


def windows_overlap(a: TemporalOverlayRow, b: TemporalOverlayRow) -> bool:
    a_starts_before_b_ends = a.effective_from is None or b.effective_to is None or a.effective_from <= b.effective_to
    b_starts_before_a_ends = b.effective_from is None or a.effective_to is None or b.effective_from <= a.effective_to
    return a_starts_before_b_ends and b_starts_before_a_ends


def resolve_statute(
    record: LawRecord, rows: list[TemporalOverlayRow], as_of: AsOf, known_ids: Collection[str] = ()
) -> StatuteView | None:
    applicable = [r for r in rows if r.status == "APPROVED" and r.statute_id == record.statute_id]
    unresolved: list[UnresolvedOverlay] = []
    covering: dict[str, list[tuple[TemporalOverlayRow, date]]] = defaultdict(list)
    has_in_force_rows = False
    for row in applicable:
        day = as_of.key_dates.get(row.keyed_on)
        if day is None:
            reason = f"the case has no {row.keyed_on} date"
            unresolved.append(UnresolvedOverlay(**_ids(row), reason=reason))
            continue
        if row.parameter == IN_FORCE_PARAMETER:
            if not isinstance(row.value, bool):
                raise OverlayConflictError(f"{row.overlay_id}: {IN_FORCE_PARAMETER} needs a boolean value")
            has_in_force_rows = True
        if covers(row, day):
            covering[row.parameter].append((row, day))

    for parameter, found in covering.items():
        if len(found) > 1:
            ids = sorted(r.overlay_id for r, _ in found)
            raise OverlayConflictError(f"{record.statute_id}: rows {ids} all apply to {parameter} on the same date")

    in_force = covering.get(IN_FORCE_PARAMETER, [])
    if has_in_force_rows and not (in_force and in_force[0][0].value is True):
        return None
    applied = [
        AppliedOverlay(**_ids(row), value=row.value) for parameter in sorted(covering) for row, _ in covering[parameter]
    ]
    return StatuteView(
        statute_id=record.statute_id,
        record=record,
        in_force="CONFIRMED" if in_force else "UNVERIFIED",
        applied=applied,
        unresolved=unresolved,
        related_ids=[i for i in record.intersecting_statute_ids if i in known_ids],
    )


def _ids(row: TemporalOverlayRow) -> dict[str, str]:
    return {"overlay_id": row.overlay_id, "parameter": row.parameter, "keyed_on": row.keyed_on}
