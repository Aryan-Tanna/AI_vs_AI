"""get_statute(id, as_of) semantics (SPEC I3-3, DATA_FORMATS §3): a section not in force on the date its
APPROVED overlay rows key on is hidden; other approved parameters are applied for that date.

Statutes, rows and dates are synthetic placeholders, not law.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from lexarena.schemas.law import LawRecord
from lexarena.schemas.overlay import TemporalOverlayRow
from lexarena.storage.temporal import AsOf, OverlayConflictError, resolve_statute
from tests.test_law_validation import law_record

STATUTE = "TEST_ACT_SEC_1"


def record() -> LawRecord:
    return LawRecord.model_validate(law_record(STATUTE))


def row(
    overlay_id: str, parameter: str, value: Any, start: str | None, end: str | None, **kw: Any
) -> TemporalOverlayRow:
    base: dict[str, Any] = {
        "overlay_id": overlay_id,
        "statute_id": STATUTE,
        "parameter": parameter,
        "value": value,
        "keyed_on": "FILING",
        "effective_from": start,
        "effective_to": end,
        "source_ref": "<ref>",
        "source_text": "<text>",
        "status": "APPROVED",
        "approved_by": "<reviewer>",
        "version": 1,
    }
    return TemporalOverlayRow.model_validate({**base, **kw})


def on(day: str, label: str = "FILING") -> AsOf:
    return AsOf(key_dates={label: date.fromisoformat(day)})


def test_no_rows_means_visible_but_unverified() -> None:
    view = resolve_statute(record(), [], on("2000-01-01"))
    assert view is not None
    assert (view.in_force, view.applied, view.unresolved) == ("UNVERIFIED", [], [])


def test_section_inserted_later_is_hidden_before_insertion() -> None:
    rows = [row("ov1", "section_in_force", True, "2001-01-01", None)]
    assert resolve_statute(record(), rows, on("2000-12-31")) is None
    view = resolve_statute(record(), rows, on("2001-01-01"))
    assert view is not None and view.in_force == "CONFIRMED"


def test_section_outside_its_window_is_hidden() -> None:
    rows = [row("ov1", "section_in_force", True, "2001-01-01", "2002-12-31")]
    assert resolve_statute(record(), rows, on("2003-01-01")) is None


def test_section_omitted_is_hidden_after_omission() -> None:
    rows = [
        row("ov1", "section_in_force", True, None, "2004-12-31"),
        row("ov2", "section_in_force", False, "2005-01-01", None),
    ]
    assert resolve_statute(record(), rows, on("2004-12-31")) is not None
    assert resolve_statute(record(), rows, on("2005-01-01")) is None


def test_missing_key_date_is_reported_never_guessed() -> None:
    rows = [row("ov1", "section_in_force", True, "2001-01-01", None, keyed_on="DEFAULT")]
    view = resolve_statute(record(), rows, on("2000-01-01", label="FILING"))
    assert view is not None and view.in_force == "UNVERIFIED"
    assert [(u.overlay_id, u.keyed_on) for u in view.unresolved] == [("ov1", "DEFAULT")]


def test_only_approved_rows_for_this_statute_count() -> None:
    rows = [
        row("draft", "section_in_force", False, None, None, status="DRAFT", approved_by=None),
        row("retired", "section_in_force", False, None, None, status="RETIRED"),
        row("other", "section_in_force", False, None, None, statute_id="TEST_ACT_SEC_2"),
    ]
    view = resolve_statute(record(), rows, on("2000-01-01"))
    assert view is not None and view.in_force == "UNVERIFIED"


def test_other_parameters_apply_for_the_keyed_date() -> None:
    rows = [
        row("old", "minimum_default_inr", 1, None, "2009-12-31"),
        row("new", "minimum_default_inr", 2, "2010-01-01", None),
    ]
    view = resolve_statute(record(), rows, on("2010-06-01"))
    assert view is not None
    [applied] = view.applied
    assert (applied.overlay_id, applied.value, applied.keyed_on) == ("new", 2, "FILING")


def test_overlapping_rows_for_one_parameter_are_a_data_error() -> None:
    rows = [
        row("a", "minimum_default_inr", 1, None, None),
        row("b", "minimum_default_inr", 2, "2010-01-01", None),
    ]
    with pytest.raises(OverlayConflictError, match="minimum_default_inr"):
        resolve_statute(record(), rows, on("2010-06-01"))


def test_in_force_value_must_be_boolean() -> None:
    with pytest.raises(OverlayConflictError, match="boolean"):
        resolve_statute(record(), [row("a", "section_in_force", "yes", None, None)], on("2000-01-01"))


def test_as_of_for_case_adds_the_decision_date() -> None:
    from tests import builders

    case = builders.case("TESTCASE_0001", date_marker="1999-12-31")
    as_of = AsOf.for_case(case)
    assert as_of.key_dates["DECISION"] == date(1999, 12, 31)
    assert as_of.key_dates["FILING"] == date.fromisoformat(builders.PLACEHOLDER_DATE)
