"""THEMIS-LOCAL layer 1: the predicate engine (BUILD_PLAN Step 7; DATA_FORMATS §4; SPEC D1, D2, D8; D-021, D-022).

One generic engine compiles any approved expression to Z3 as a tracked assertion named by its error code. Inputs
come from the case record, the law as of the case date, overlay rows and the argument's own claims. A missing input
or an unchosen reading skips the predicate (it goes to layer 2); it never rejects. Placeholder statutes and values.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from lexarena.schemas.predicate import PredicateEntry
from lexarena.themis_local.predicates import Inputs, evaluate, resolve_inputs, select_approved

HASH = "0" * 64


def predicate(expression: dict[str, Any], inputs: list[dict[str, str]], **change: Any) -> PredicateEntry:
    base: dict[str, Any] = {
        "predicate_id": "PR-T",
        "statute_id": "TEST_ACT_SEC_7",
        "field": "financial_threshold",
        "item_index": None,
        "item_hash": HASH,
        "kind": "THRESHOLD",
        "inputs": inputs,
        "open_parameters": [],
        "expression": expression,
        "error_code": "ERR_THRESHOLD_APPLICATION",
        "source_text": "<source>",
        "status": "APPROVED",
        "approved_by": "<owner>",
        "version": 1,
    }
    base.update(change)
    return PredicateEntry.model_validate(base)


THRESHOLD = predicate(
    {"op": "==", "args": [{"var": "says_met"}, {"op": ">=", "args": [{"var": "amount"}, {"var": "minimum"}]}]},
    [
        {"name": "says_met", "source": "claim:asserts_threshold_met"},
        {"name": "amount", "source": "record.amounts:CLAIMED_DEFAULT"},
        {"name": "minimum", "source": "overlay:minimum_default_inr"},
    ],
)


def values(**claim: Any) -> Inputs:
    return resolve_inputs(
        THRESHOLD,
        amounts={"CLAIMED_DEFAULT": 6_000_000},
        key_dates={},
        law={},
        overlay={"minimum_default_inr": 10_000_000},
        claim=claim,
    )


def test_an_accurate_claim_passes() -> None:
    assert evaluate(THRESHOLD, values(asserts_threshold_met=False), choices={}).status == "PASS"


def test_a_misapplied_threshold_fails_with_its_error_code() -> None:
    result = evaluate(THRESHOLD, values(asserts_threshold_met=True), choices={})
    assert result.status == "FAIL" and result.error_code == "ERR_THRESHOLD_APPLICATION"


def test_a_missing_input_skips_the_predicate_never_rejects() -> None:
    result = evaluate(THRESHOLD, values(), choices={})
    assert result.status == "SKIPPED" and result.missing == ["says_met"]


LIMITATION = predicate(
    {
        "op": "==",
        "args": [
            {"var": "says_within"},
            {"op": "<=", "args": [{"var": "filed"}, {"op": "add_years", "args": [{"var": "default"}, {"const": 3}]}]},
        ],
    },
    [
        {"name": "says_within", "source": "claim:asserts_within_limitation"},
        {"name": "filed", "source": "record.key_dates:FILING"},
        {"name": "default", "source": "record.key_dates:DEFAULT"},
    ],
    kind="DATE_WINDOW",
    field="procedural_timelines",
    error_code="ERR_TIMELINE_MISSTATED",
)


@pytest.mark.parametrize(
    ("default", "filed", "within"),
    [
        (date(2001, 2, 28), date(2004, 2, 28), True),  # the last day of three calendar years
        (date(2001, 2, 28), date(2004, 2, 29), False),
        (date(2000, 2, 29), date(2003, 2, 28), True),  # a leap-day start ends on 28 February
        (date(2003, 6, 1), date(2006, 6, 1), True),  # crosses 29.02.2004: 1,095 days would end on 31.05.2006
    ],
)
def test_calendar_years_not_day_counts(default: date, filed: date, within: bool) -> None:
    inputs = resolve_inputs(
        LIMITATION,
        amounts={},
        key_dates={"FILING": filed, "DEFAULT": default},
        law={},
        overlay={},
        claim={"asserts_within_limitation": within},
    )
    assert evaluate(LIMITATION, inputs, choices={}).status == "PASS"
    flipped = {**inputs, "says_within": not within}
    assert evaluate(LIMITATION, flipped, choices={}).status == "FAIL"


OPEN = predicate(
    {
        "op": "choose",
        "param": "cutoff_basis",
        "cases": {
            "COMMENCEMENT": {
                "op": "==",
                "args": [{"var": "says"}, {"op": "<", "args": [{"var": "reg"}, {"var": "start"}]}],
            },
            "SUBMISSION": {
                "op": "==",
                "args": [{"var": "says"}, {"op": "<", "args": [{"var": "reg"}, {"var": "plan"}]}],
            },
        },
    },
    [
        {"name": "says", "source": "claim:asserts_exemption"},
        {"name": "reg", "source": "record.key_dates:REGISTRATION"},
        {"name": "start", "source": "record.key_dates:CIRP_COMMENCEMENT"},
        {"name": "plan", "source": "record.key_dates:PLAN_SUBMISSION"},
    ],
    open_parameters=[{"name": "cutoff_basis", "options": ["COMMENCEMENT", "SUBMISSION"], "note": "<open reading>"}],
    kind="DATE_ORDER",
)


def test_each_side_may_choose_its_reading_and_is_held_only_to_it() -> None:
    dates = {
        "REGISTRATION": date(2002, 5, 1),
        "CIRP_COMMENCEMENT": date(2002, 2, 1),
        "PLAN_SUBMISSION": date(2002, 7, 1),
    }
    exempt = resolve_inputs(OPEN, amounts={}, key_dates=dates, law={}, overlay={}, claim={"asserts_exemption": True})
    assert evaluate(OPEN, exempt, choices={"cutoff_basis": "SUBMISSION"}).status == "PASS"
    assert evaluate(OPEN, exempt, choices={"cutoff_basis": "COMMENCEMENT"}).status == "FAIL"
    assert evaluate(OPEN, exempt, choices={}).status == "SKIPPED"  # no reading chosen: layer 2, never a rejection


def test_law_inputs_read_a_json_path_of_the_record() -> None:
    p = predicate(
        {"op": "==", "args": [{"var": "claimed"}, {"var": "law_days"}]},
        [
            {"name": "claimed", "source": "claim:window_days"},
            {"name": "law_days", "source": "law:procedural_timelines.adjudication_window_days"},
        ],
        kind="DAY_COUNT",
        field="procedural_timelines",
        error_code="ERR_TIMELINE_MISSTATED",
    )
    law = {"procedural_timelines": {"adjudication_window_days": 14}}
    ok = resolve_inputs(p, amounts={}, key_dates={}, law=law, overlay={}, claim={"window_days": 14})
    bad = resolve_inputs(p, amounts={}, key_dates={}, law=law, overlay={}, claim={"window_days": 30})
    assert evaluate(p, ok, choices={}).status == "PASS" and evaluate(p, bad, choices={}).status == "FAIL"


def test_days_between_and_add_days() -> None:
    p = predicate(
        {
            "op": "==",
            "args": [
                {"var": "says_late"},
                {
                    "op": ">",
                    "args": [{"op": "days_between", "args": [{"var": "notice"}, {"var": "filed"}]}, {"const": 10}],
                },
            ],
        },
        [
            {"name": "says_late", "source": "claim:asserts_after_period"},
            {"name": "notice", "source": "record.key_dates:DEMAND_NOTICE"},
            {"name": "filed", "source": "record.key_dates:FILING"},
        ],
        kind="DAY_COUNT",
        field="procedural_timelines",
        error_code="ERR_TIMELINE_MISSTATED",
    )
    dates = {"DEMAND_NOTICE": date(2001, 1, 1), "FILING": date(2001, 1, 12)}
    inputs = resolve_inputs(p, amounts={}, key_dates=dates, law={}, overlay={}, claim={"asserts_after_period": True})
    assert evaluate(p, inputs, choices={}).status == "PASS"


def test_only_approved_current_predicates_are_used() -> None:
    draft = THRESHOLD.model_copy(update={"status": "DRAFT", "approved_by": None, "predicate_id": "PR-D"})
    stale = THRESHOLD.model_copy(update={"status": "STALE", "predicate_id": "PR-S"})
    assert [p.predicate_id for p in select_approved([THRESHOLD, draft, stale])] == ["PR-T"]
