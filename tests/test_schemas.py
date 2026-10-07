"""Validation rules of the project-owned schemas (SPEC H, side collections, lessons)."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from lexarena.schemas.case import AgentView, Case
from lexarena.schemas.lesson import Lesson
from lexarena.schemas.overlay import TemporalOverlayRow
from lexarena.schemas.predicate import PredicateEntry
from lexarena.schemas.session import Session
from lexarena.schemas.transcript import ThemisLocalResult
from tests import builders

# ---------------------------------------------------------------- cases (H1)


def _case_doc() -> dict[str, Any]:
    return builders.case_doc("TESTCASE_0001")


def test_builder_case_is_valid_and_round_trips() -> None:
    case = Case.model_validate(_case_doc())
    assert Case.model_validate(case.to_document()) == case


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("record", "amounts", 0, "fact_id"), "F9", "dangling"),
        (("record", "exhibits", 0, "filed_by"), "Z9", "dangling"),
        (("metadata", "key_dates", 0, "fact_id"), "C9", "dangling"),
        (("opening_positions", "RESPONDENT", 0, "issue_id"), "I9", "dangling"),
        (("parties", 1, "represented_by_agent"), "LEX_P", "must be represented by LEX_D"),
        (("parties", 1, "simulation_side"), "PETITIONER", "at least one PETITIONER and one RESPONDENT"),
        (("record", "stipulated_facts", 0, "source_paras"), [], "at least 1"),
        (("record", "exhibits", 0, "source_paras"), [], "at least 1"),
        (("record", "contested_facts", 0, "fact_id"), "F1", "pattern"),
        (("lower_forum_order", "exists"), False, "exists is false"),
    ],
)
def test_agent_view_rejects(path: tuple[str | int, ...], value: object, message: str) -> None:
    doc = copy.deepcopy(_case_doc()["agent_view"])
    target: Any = doc
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    if path == ("parties", 1, "simulation_side"):
        doc["parties"][1]["represented_by_agent"] = "LEX_P"
    with pytest.raises(ValidationError, match=message):
        AgentView.model_validate(doc)


def test_duplicate_ids_rejected() -> None:
    doc = copy.deepcopy(_case_doc()["agent_view"])
    doc["record"]["stipulated_facts"].append(dict(doc["record"]["stipulated_facts"][0]))
    with pytest.raises(ValidationError, match="duplicate fact IDs"):
        AgentView.model_validate(doc)


def test_unknown_field_rejected_in_owned_formats() -> None:
    doc = _case_doc()
    doc["agent_view"]["outcome_hint"] = "<x>"
    with pytest.raises(ValidationError, match="Extra inputs"):
        Case.model_validate(doc)


# ---------------------------------------------------------------- transcript and sessions (H3, H4)


def _themis(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "outcome": "PASS",
        "attempts": 1,
        "hard_errors_by_attempt": [[]],
        "warnings": [],
        "s_local": 1.0,
    }
    return {**base, **overrides}


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"outcome": "REVISE"}, "Input should be"),
        ({"outcome": "FLAGGED"}, "FLAGGED if and only if"),
        ({"attempts": 2}, "one entry per attempt"),
        ({"hard_errors_by_attempt": [["ERR_THRESHOLD_MISSTATED"]]}, "FLAGGED if and only if"),
        ({"hard_errors_by_attempt": [["ERR_NOT_A_D8_CODE"]]}, "Input should be"),
        ({"outcome": "PASS_WITH_NOTES"}, "needs at least one warning"),
        ({"warnings": [{"code": "UNMAPPED"}]}, "PASS has no warnings"),
    ],
)
def test_themis_outcome_rules(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        ThemisLocalResult.model_validate(_themis(**overrides))


def test_flagged_with_final_hard_error_is_valid() -> None:
    result = ThemisLocalResult.model_validate(
        _themis(
            outcome="FLAGGED",
            attempts=2,
            hard_errors_by_attempt=[["ERR_FACT_NOT_IN_RECORD"], ["ERR_FACT_NOT_IN_RECORD"]],
        )
    )
    assert result.outcome == "FLAGGED"


def test_session_winner_only_with_recorded_verdict() -> None:
    doc = builders.session("S1", "TESTCASE_0001").to_document()
    doc["winner"] = "PETITIONER"
    doc["aggregate"] = {"PETITIONER": 1.0, "RESPONDENT": 0.0}
    with pytest.raises(ValidationError, match="verdict is recorded"):
        Session.model_validate(doc)
    doc["state"] = "VERDICT_RECORDED"
    assert Session.model_validate(doc).winner == "PETITIONER"


# ---------------------------------------------------------------- side collections (DATA_FORMATS §3, §4)


def _predicate(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "predicate_id": "<pred>",
        "statute_id": "<statute>",
        "field": "financial_threshold",
        "item_index": None,
        "item_hash": "0" * 64,
        "kind": "THRESHOLD",
        "inputs": [
            {"name": "claimed", "source": "claim:financial_threshold.minimum_amount"},
            {"name": "law", "source": "overlay:minimum_default_inr"},
        ],
        "open_parameters": [],
        "expression": {"op": "==", "args": [{"var": "claimed"}, {"var": "law"}]},
        "error_code": "ERR_THRESHOLD_MISSTATED",
        "source_text": "<source text>",
        "status": "DRAFT",
        "approved_by": None,
        "version": 1,
    }
    return {**base, **overrides}


def test_valid_predicate() -> None:
    assert PredicateEntry.model_validate(_predicate()).error_code == "ERR_THRESHOLD_MISSTATED"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"expression": {"op": ">=", "args": [{"var": "law"}, {"const": 1}]}}, r"claim: input \(D-021\)"),
        ({"expression": {"op": "==", "args": [{"var": "claimed"}, {"var": "nope"}]}}, "undeclared input"),
        ({"expression": {"op": "not", "args": [{"var": "claimed"}, {"var": "law"}]}}, "takes 1..1 arguments"),
        ({"error_code": "ERR_BELOW_MINIMUM_DEFAULT_THRESHOLD"}, "Input should be"),
        ({"inputs": [{"name": "claimed", "source": "case_ground_truth:x"}]}, "pattern"),
        ({"status": "APPROVED"}, "approved_by"),
        (
            {
                "open_parameters": [{"name": "reading", "options": ["A", "B"], "note": ""}],
                "expression": {"op": "choose", "param": "reading", "cases": {"A": {"var": "claimed"}}},
            },
            "cover exactly its options",
        ),
    ],
)
def test_predicate_rules(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        PredicateEntry.model_validate(_predicate(**overrides))


def test_choose_over_open_parameter_is_valid() -> None:
    entry = PredicateEntry.model_validate(
        _predicate(
            open_parameters=[{"name": "reading", "options": ["A", "B"], "note": "<note>"}],
            expression={
                "op": "choose",
                "param": "reading",
                "cases": {
                    "A": {"op": "==", "args": [{"var": "claimed"}, {"var": "law"}]},
                    "B": {"op": ">=", "args": [{"var": "claimed"}, {"var": "law"}]},
                },
            },
        )
    )
    assert entry.open_parameters[0].options == ["A", "B"]


def _overlay(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "overlay_id": "<ov>",
        "statute_id": "<statute>",
        "parameter": "section_in_force",
        "value": True,
        "keyed_on": "DECISION",
        "effective_from": builders.PLACEHOLDER_DATE,
        "effective_to": None,
        "source_ref": "<ref>",
        "source_text": "<text>",
        "status": "DRAFT",
        "approved_by": None,
        "version": 1,
    }
    return {**base, **overrides}


def test_overlay_keeps_booleans_and_date_ranges() -> None:
    assert TemporalOverlayRow.model_validate(_overlay()).value is True
    ranged = TemporalOverlayRow.model_validate(_overlay(value={"from": "2000-01-01", "to": "2000-02-01"}))
    assert ranged.to_document()["value"] == {"from": "2000-01-01", "to": "2000-02-01"}


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"status": "APPROVED"}, "approved_by"),
        ({"effective_to": "1990-01-01"}, "after effective_to"),
        ({"value": {"from": "2000-02-01", "to": "2000-01-01"}}, "after 'to'"),
        ({"source_text": ""}, "at least 1"),
        ({"keyed_on": "FILING"}, "section_in_force must key on DECISION"),
    ],
)
def test_overlay_rules(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        TemporalOverlayRow.model_validate(_overlay(**overrides))


# ---------------------------------------------------------------- lessons (DATA_FORMATS §5)


def _lesson(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "lesson_id": "<L>",
        "lesson_type": "ADVOCACY",
        "memory": "LAWYER",
        "party_status": "FINANCIAL_CREDITOR",
        "statute_ids": [],
        "error_code": None,
        "trigger": "<trigger>",
        "lesson": "<lesson>",
        "provenance": {"case_id": "<case>", "issue_ids": ["I1"], "source_paras": ["1"]},
        "driver": "LAW",
        "severity": 1,
        "frequency": 1,
        "confidence": 0.5,
        "last_retrieved_case_seq": 0,
        "status": "ACTIVE",
        "created_in_run": "<run>",
    }
    return {**base, **overrides}


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"memory": "JUDGE", "party_status": None}, "LEGAL_RULE lessons only"),
        ({"party_status": None}, "keyed by party_status"),
        ({"lesson_type": "PROCEDURAL_ERROR"}, "tied to an error code"),
        ({"driver": "EVIDENCE"}, "Input should be 'LAW'"),
        ({"lesson_type": "LEGAL_RULE", "memory": "JUDGE"}, "carry no party_status"),
        ({"provenance": {"case_id": "<c>", "issue_ids": [], "source_paras": ["1"]}}, "at least 1"),
    ],
)
def test_lesson_rules(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Lesson.model_validate(_lesson(**overrides))
