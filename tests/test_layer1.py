"""THEMIS-LOCAL layer 1 over a whole argument (BUILD_PLAN Step 7; SPEC D1, D2, D3, D8; D-062, D-063).

Each statute the argument relies on gets the D1 audit plus its approved, current predicates; the limitation
article also gets the date chain as a warning. Placeholder statutes and values.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from lexarena.config import load_config
from lexarena.schemas.case import Amount
from lexarena.schemas.law import LawRecord, checklist_item, item_hash
from lexarena.schemas.overlay import DateRange
from lexarena.schemas.predicate import PredicateEntry
from lexarena.schemas.transcript import ExtractedChecklist
from lexarena.storage.temporal import AppliedOverlay, StatuteView
from lexarena.themis_local.layer1 import CaseFacts, run_layer1
from tests.conftest import CONFIG_V1
from tests.test_law_validation import law_record
from tests.test_statute_audit import claim

CFG = load_config(CONFIG_V1).themis_local
LIM = CFG.limitation
LIMITATION_ID = "TEST_LIMITATION_ART_1"
FACTS = CaseFacts(
    amounts={
        "AM1": Amount(amount_id="AM1", label="DEFAULT", value_inr=6_000_000, date=None, party_id=None, fact_id="F1")
    },
    key_dates={LIM.default_date_label: date(2001, 6, 1), LIM.filing_date_label: date(2005, 1, 1)},
    date_fact_ids={LIM.default_date_label: "F2", LIM.filing_date_label: "F3"},
)


def statute_view(statute_id: str, applied: dict[str, Any] | None = None) -> StatuteView:
    raw = law_record(statute_id)
    raw["procedural_timelines"] = {"adjudication_window_days": 14, "rectification_window_days": 7}
    return StatuteView(
        statute_id=statute_id,
        record=LawRecord.model_validate(raw),
        in_force="UNVERIFIED",
        applied=[
            AppliedOverlay(overlay_id=f"OV_{k}", parameter=k, value=v, keyed_on="FILING")
            for k, v in (applied or {}).items()
        ],
        unresolved=[],
        related_ids=[],
    )


def window_predicate(record: LawRecord, **change: Any) -> PredicateEntry:
    """A predicate on the adjudication window: the argument's stated window must equal the law's."""
    base: dict[str, Any] = {
        "predicate_id": "PR-W",
        "statute_id": record.statute_id,
        "field": "adjudication_window_days",
        "item_index": None,
        "item_hash": item_hash(checklist_item(record, "adjudication_window_days", None)),
        "kind": "DAY_COUNT",
        "inputs": [
            {"name": "stated", "source": "claim:procedural_timelines.adjudication_window_days"},
            {"name": "law", "source": "law:procedural_timelines.adjudication_window_days"},
        ],
        "open_parameters": [],
        "expression": {"op": "==", "args": [{"var": "stated"}, {"var": "law"}]},
        "error_code": "ERR_TIMELINE_MISSTATED",
        "source_text": "<source>",
        "status": "APPROVED",
        "approved_by": "<owner>",
        "version": 1,
    }
    base.update(change)
    return PredicateEntry.model_validate(base)


def for_statute(statute_id: str, **change: Any) -> ExtractedChecklist:
    return claim(**change).model_copy(update={"statute_id": statute_id})


def test_each_statute_is_audited_and_errors_are_collected() -> None:
    views = {"A_SEC_1": statute_view("A_SEC_1"), "B_SEC_2": statute_view("B_SEC_2")}
    checklists = [
        for_statute("A_SEC_1", rectification_window_days=7),
        for_statute("B_SEC_2", rectification_window_days=30),
    ]
    result = run_layer1(checklists, views, {}, FACTS, CFG)
    assert [(e.code, e.statute_id) for e in result.hard_errors] == [("ERR_TIMELINE_MISSTATED", "B_SEC_2")]


def test_a_statute_not_visible_on_the_case_date_is_left_to_layer_2() -> None:
    result = run_layer1([for_statute("HIDDEN_SEC_9")], {}, {}, FACTS, CFG)
    assert result.hard_errors == [] and [w.code for w in result.warnings] == ["STATUTE_NOT_AVAILABLE"]


def test_approved_predicates_run_and_name_their_error_code() -> None:
    view = statute_view("A_SEC_1")
    predicates = {"A_SEC_1": [window_predicate(view.record)]}
    bad = run_layer1([for_statute("A_SEC_1", adjudication_window_days=14)], {"A_SEC_1": view}, predicates, FACTS, CFG)
    assert bad.hard_errors == []  # the audit and the predicate agree the stated window is right
    wrong = run_layer1([for_statute("A_SEC_1", adjudication_window_days=30)], {"A_SEC_1": view}, predicates, FACTS, CFG)
    assert sorted(e.code for e in wrong.hard_errors) == ["ERR_TIMELINE_MISSTATED"]  # one error per code and statute
    assert "PR-W" in wrong.hard_errors[0].detail or wrong.predicates_failed == ["PR-W"]


def test_a_draft_or_stale_predicate_never_runs() -> None:
    view = statute_view("A_SEC_1")
    draft = window_predicate(view.record, status="DRAFT", approved_by=None)
    stale = window_predicate(view.record, item_hash="f" * 64)
    for p in (draft, stale):
        result = run_layer1([for_statute("A_SEC_1")], {"A_SEC_1": view}, {"A_SEC_1": [p]}, FACTS, CFG)
        assert result.predicates_run == []


def test_a_predicate_missing_its_claim_is_unmapped_not_rejected() -> None:
    view = statute_view("A_SEC_1")
    result = run_layer1(
        [for_statute("A_SEC_1")], {"A_SEC_1": view}, {"A_SEC_1": [window_predicate(view.record)]}, FACTS, CFG
    )
    assert result.hard_errors == [] and [w.code for w in result.warnings] == ["UNMAPPED"]


def limitation_view() -> StatuteView:
    return statute_view(LIMITATION_ID, applied={LIM.period_parameter: 3})


def test_a_wrong_limitation_conclusion_is_a_warning_not_a_rejection() -> None:
    wrong = for_statute(LIMITATION_ID, asserts_within_limitation=True)  # 2001 default, 2005 filing: out of time
    result = run_layer1([wrong], {LIMITATION_ID: limitation_view()}, {}, FACTS, CFG)
    assert result.hard_errors == [] and [w.code for w in result.warnings] == ["WARN_LIMITATION_INCONSISTENT"]
    acknowledged = for_statute(LIMITATION_ID, asserts_within_limitation=True, acknowledgment_dates=[date(2003, 1, 1)])
    assert run_layer1([acknowledged], {LIMITATION_ID: limitation_view()}, {}, FACTS, CFG).warnings == []


def test_limitation_without_an_approved_period_is_not_checked() -> None:
    view = statute_view(LIMITATION_ID)
    result = run_layer1(
        [for_statute(LIMITATION_ID, asserts_within_limitation=True)], {LIMITATION_ID: view}, {}, FACTS, CFG
    )
    assert result.warnings == []


def test_an_excluded_window_comes_from_overlay_data() -> None:
    window = DateRange.model_validate({"from": date(2003, 1, 1), "to": date(2005, 6, 30)})
    view = statute_view(LIMITATION_ID, applied={LIM.period_parameter: 3, LIM.excluded_parameter: window})
    within = for_statute(LIMITATION_ID, asserts_within_limitation=True)  # the window stops the clock
    assert run_layer1([within], {LIMITATION_ID: view}, {}, FACTS, CFG).warnings == []


def test_a_value_attached_to_several_statutes_is_wrong_only_if_it_matches_none() -> None:
    # Measured 2026-10-08: the extractor copied "14 days" from a sentence about one section onto two sections.
    other = statute_view("B_SEC_2")
    other.record.procedural_timelines.adjudication_window_days = 30
    views = {"A_SEC_1": statute_view("A_SEC_1"), "B_SEC_2": other}
    honest = [for_statute("A_SEC_1", adjudication_window_days=14), for_statute("B_SEC_2", adjudication_window_days=14)]
    assert run_layer1(honest, views, {}, FACTS, CFG).hard_errors == []
    wrong = [for_statute("A_SEC_1", adjudication_window_days=21), for_statute("B_SEC_2", adjudication_window_days=21)]
    assert sorted(e.statute_id for e in run_layer1(wrong, views, {}, FACTS, CFG).hard_errors) == ["A_SEC_1", "B_SEC_2"]
