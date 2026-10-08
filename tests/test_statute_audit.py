"""THEMIS-LOCAL layer 1: the per-statute audit (BUILD_PLAN Step 7; SPEC D1, D3, D8; D-062).

The argument's checklist for one statute is checked against the Law DB entry as it applies on the case date and
against the record. Hard errors only for provable misstatements; everything uncertain is a warning or UNMAPPED, never
a rejection. Placeholder statutes, items and values.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from lexarena.config import load_config
from lexarena.schemas.case import Amount
from lexarena.schemas.config import ThemisLocalConfig
from lexarena.schemas.law import LawRecord
from lexarena.schemas.transcript import ExtractedChecklist
from lexarena.storage.temporal import AppliedOverlay, StatuteView, UnresolvedOverlay
from lexarena.themis_local.audit import audit_statute
from tests.conftest import CONFIG_V1
from tests.test_law_validation import law_record

CFG: ThemisLocalConfig = load_config(CONFIG_V1).themis_local
PARAM = CFG.threshold_overlay_parameter
MIN = 10_000_000
AMOUNTS = {
    "AM1": Amount(
        amount_id="AM1", label="DEFAULT", value_inr=6_000_000, date=date(2001, 1, 1), party_id=None, fact_id="F1"
    ),
    "AM2": Amount(amount_id="AM2", label="DEFAULT", value_inr=12_000_000, date=None, party_id=None, fact_id="F2"),
}


def view(*, applied: dict[str, Any] | None = None, unresolved: tuple[str, ...] = (), **law: Any) -> StatuteView:
    raw = law_record("TEST_ACT_SEC_7", **law)
    raw["diagnostic_checklist"]["mandatory_prerequisites"] = ["<notice>", "<default>"]
    raw["diagnostic_checklist"]["statutory_bars"] = ["<bar>"]
    raw["procedural_timelines"] = {"adjudication_window_days": 14, "rectification_window_days": 7}
    return StatuteView(
        statute_id="TEST_ACT_SEC_7",
        record=LawRecord.model_validate(raw),
        in_force="UNVERIFIED",
        applied=[
            AppliedOverlay(overlay_id=f"OV_{k}", parameter=k, value=v, keyed_on="FILING")
            for k, v in (applied or {}).items()
        ],
        unresolved=[
            UnresolvedOverlay(overlay_id=f"OV_{k}", parameter=k, keyed_on="FILING", reason="<no date>")
            for k in unresolved
        ],
        related_ids=[],
    )


def item(law_index: int | None, confidence: float = 0.9, quote: str = "<quoted span>") -> dict[str, Any]:
    return {"law_index": law_index, "quote": quote, "confidence": confidence}


def claim(**change: Any) -> ExtractedChecklist:
    base: dict[str, Any] = {
        "statute_id": "TEST_ACT_SEC_7",
        "stance": "INVOKE_BAR",
        "asserts_threshold_met": None,
        "threshold_amount_id": None,
        "diagnostic_checklist": {
            "applicant_eligibility": [],
            "financial_threshold": {"minimum_amount": None, "currency": None},
            "mandatory_prerequisites": [],
            "statutory_bars": [],
            "saving_exceptions": [],
        },
        "procedural_timelines": {"adjudication_window_days": None, "rectification_window_days": None},
    }
    for key, value in change.items():
        if key in base["diagnostic_checklist"]:
            base["diagnostic_checklist"][key] = value
        elif key in base["procedural_timelines"]:
            base["procedural_timelines"][key] = value
        else:
            base[key] = value
    return ExtractedChecklist.model_validate(base)


def codes(result: Any) -> tuple[list[str], list[str]]:
    return [e.code for e in result.hard_errors], [w.code for w in result.warnings]


def threshold(amount: float) -> dict[str, Any]:
    return {"minimum_amount": amount, "currency": "INR"}


# ---------------------------------------------------------------- thresholds


def test_an_accurately_stated_threshold_passes() -> None:
    result = audit_statute(view(applied={PARAM: MIN}), claim(financial_threshold=threshold(1e7)), AMOUNTS, CFG)
    assert codes(result) == ([], [])


def test_a_misstated_threshold_is_a_hard_error() -> None:
    result = audit_statute(view(applied={PARAM: MIN}), claim(financial_threshold=threshold(100_000)), AMOUNTS, CFG)
    assert codes(result)[0] == ["ERR_THRESHOLD_MISSTATED"]


def test_without_an_approved_dated_value_a_threshold_is_never_rejected() -> None:
    # A filing before a notification raised the threshold: no approved row covers the date, and the Law DB only
    # stores today's figure. An honest counsel citing the older figure must not be rejected (INTENT fear 4).
    stored: dict[str, Any] = {
        "diagnostic_checklist": {**law_record("X")["diagnostic_checklist"], "financial_threshold": threshold(MIN)}
    }
    for v in (view(**stored), view(unresolved=(PARAM,), **stored)):
        result = audit_statute(v, claim(financial_threshold=threshold(100_000)), AMOUNTS, CFG)
        hard, warnings = codes(result)
        assert hard == [] and warnings == ["THRESHOLD_NOT_VERIFIABLE"]


@pytest.mark.parametrize(
    ("amount_id", "says_met", "expected"),
    [
        ("AM1", False, []),
        ("AM2", True, []),
        ("AM1", True, ["ERR_THRESHOLD_APPLICATION"]),
        ("AM2", False, ["ERR_THRESHOLD_APPLICATION"]),
    ],
)
def test_threshold_application_against_the_record(amount_id: str, says_met: bool, expected: list[str]) -> None:
    c = claim(asserts_threshold_met=says_met, threshold_amount_id=amount_id)
    assert codes(audit_statute(view(applied={PARAM: MIN}), c, AMOUNTS, CFG))[0] == expected


@pytest.mark.parametrize("amount_id", [None, "AM9"])
def test_an_unknown_or_missing_amount_is_unmapped_not_rejected(amount_id: str | None) -> None:
    c = claim(asserts_threshold_met=True, threshold_amount_id=amount_id)
    hard, warnings = codes(audit_statute(view(applied={PARAM: MIN}), c, AMOUNTS, CFG))
    assert hard == [] and warnings == ["UNMAPPED"]


def test_a_threshold_in_another_currency_is_unmapped() -> None:
    c = claim(financial_threshold={"minimum_amount": 100_000, "currency": "USD"})
    hard, warnings = codes(audit_statute(view(applied={PARAM: MIN}), c, AMOUNTS, CFG))
    assert hard == [] and warnings == ["UNMAPPED"]


# ---------------------------------------------------------------- timelines


def test_timelines_checked_against_the_law_db() -> None:
    good = audit_statute(view(), claim(adjudication_window_days=14, rectification_window_days=7), AMOUNTS, CFG)
    bad = audit_statute(view(), claim(rectification_window_days=30), AMOUNTS, CFG)
    assert codes(good) == ([], []) and codes(bad)[0] == ["ERR_TIMELINE_MISSTATED"]


def test_a_dated_overlay_value_replaces_the_stored_timeline() -> None:
    result = audit_statute(
        view(applied={"adjudication_window_days": 30}), claim(adjudication_window_days=30), AMOUNTS, CFG
    )
    assert codes(result) == ([], [])


def test_an_unresolved_dated_timeline_is_not_checked() -> None:
    result = audit_statute(
        view(unresolved=("adjudication_window_days",)), claim(adjudication_window_days=99), AMOUNTS, CFG
    )
    hard, warnings = codes(result)
    assert hard == [] and warnings == ["UNMAPPED"]


# ---------------------------------------------------------------- checklist items


def test_low_confidence_unquoted_or_out_of_range_items_are_unmapped() -> None:
    c = claim(statutory_bars=[item(0, confidence=0.5), item(0, quote=""), item(7)])
    hard, warnings = codes(audit_statute(view(), c, AMOUNTS, CFG))
    assert hard == [] and warnings == ["UNMAPPED"] * 3


def test_a_condition_not_in_the_statute_is_a_warning() -> None:
    hard, warnings = codes(audit_statute(view(), claim(statutory_bars=[item(None)]), AMOUNTS, CFG))
    assert hard == [] and warnings == ["WARN_CONDITION_NOT_IN_STATUTE"]


def test_asserting_a_claim_with_prerequisites_unaddressed_is_a_warning() -> None:
    result = audit_statute(view(), claim(stance="ASSERT_CLAIM", mandatory_prerequisites=[item(1)]), AMOUNTS, CFG)
    assert codes(result) == ([], ["WARN_PREREQUISITE_UNADDRESSED"])
    assert result.warnings[0].law_indices == [0]
    covered = claim(stance="ASSERT_CLAIM", mandatory_prerequisites=[item(0), item(1)])
    assert codes(audit_statute(view(), covered, AMOUNTS, CFG)) == ([], [])


def test_hard_errors_carry_the_statute_and_record_ids_for_retry_feedback() -> None:
    c = claim(asserts_threshold_met=True, threshold_amount_id="AM1")
    error = audit_statute(view(applied={PARAM: MIN}), c, AMOUNTS, CFG).hard_errors[0]
    assert error.statute_id == "TEST_ACT_SEC_7" and error.record_ids == ["AM1"]
