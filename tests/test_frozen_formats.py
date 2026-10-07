"""Frozen formats (DATA_FORMATS §1-2): strict on documented fields, preserve-and-report on anything else.

The base records are real records taken from the data files at test time, then modified; no test
depends on what the files contain beyond one record existing (D-033).
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from pydantic import ValidationError

from lexarena.schemas.law import LawRecord
from lexarena.schemas.precedent import PrecedentRecord
from tests.conftest import REPO_ROOT

LAW_FILES = sorted((REPO_ROOT / "data" / "law_db").glob("*.json"))


@pytest.fixture(scope="module")
def law_record() -> dict[str, Any]:
    if not LAW_FILES:
        pytest.skip("no Law DB files")
    first: dict[str, Any] = json.loads(LAW_FILES[0].read_text(encoding="utf-8"))[0]
    return first


@pytest.fixture(scope="module")
def precedent_record() -> dict[str, Any]:
    for path in sorted((REPO_ROOT / "data" / "precedents").rglob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and set(PrecedentRecord.model_fields) <= set(value):
                return value
    pytest.skip("no precedent record on its own line")


def test_real_law_record_validates_and_round_trips(law_record: dict[str, Any]) -> None:
    record = LawRecord.model_validate(law_record)
    assert record.to_document() == law_record


def test_law_number_given_as_text_is_rejected(law_record: dict[str, Any]) -> None:
    doc = copy.deepcopy(law_record)
    doc["procedural_timelines"]["adjudication_window_days"] = "14"
    with pytest.raises(ValidationError, match="adjudication_window_days"):
        LawRecord.model_validate(doc)


def test_law_id_must_equal_statute_id(law_record: dict[str, Any]) -> None:
    doc = {**law_record, "statute_id": law_record["statute_id"] + "_X"}
    with pytest.raises(ValidationError, match="must equal statute_id"):
        LawRecord.model_validate(doc)


def test_missing_documented_field_is_rejected(law_record: dict[str, Any]) -> None:
    doc = {k: v for k, v in law_record.items() if k != "core_judicial_inquiry"}
    with pytest.raises(ValidationError, match="core_judicial_inquiry"):
        LawRecord.model_validate(doc)


def test_undocumented_fields_are_kept_and_reported_at_any_depth(law_record: dict[str, Any]) -> None:
    doc = copy.deepcopy(law_record)
    doc["zz_probe_top"] = "<kept>"
    doc["diagnostic_checklist"]["zz_probe_nested"] = ["<kept>"]
    record = LawRecord.model_validate(doc)
    assert sorted(record.undocumented_fields()) == ["diagnostic_checklist.zz_probe_nested", "zz_probe_top"]
    assert record.to_document() == doc  # preserved, not dropped


def test_real_precedent_record_validates_and_round_trips(precedent_record: dict[str, Any]) -> None:
    record = PrecedentRecord.model_validate(precedent_record)
    assert record.to_document() == precedent_record


@pytest.mark.parametrize(
    ("field", "value", "kind"),
    [
        ("decision_date", "<not a date>", "decision_date is not YYYY-MM-DD"),
        ("decision_date", "20200101", "decision_date is not YYYY-MM-DD"),
        ("forum", "<other forum>", "forum is not one of"),
    ],
)
def test_precedent_format_issues_are_reported_not_rejected(
    precedent_record: dict[str, Any], field: str, value: str, kind: str
) -> None:
    record = PrecedentRecord.model_validate({**precedent_record, field: value})
    assert any(k.startswith(kind) and v == value for k, v in record.format_issues())
    assert record.parsed_decision_date() is None or field != "decision_date"


def test_precedent_overruled_flag_must_be_boolean(precedent_record: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="is_overruled"):
        PrecedentRecord.model_validate({**precedent_record, "is_overruled": "false"})
