"""Public case DB schema + cross-file validator. Each mutation of the valid example must be caught."""
import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from lexarena.public_db_validate import validate_dir
from lexarena.schemas.public_case import PublicGroundTruth, PublicManifest, PublicUnspoiled

EXAMPLE = Path(__file__).resolve().parent.parent / "docs" / "schema" / "example"


def load(name):
    return json.loads((EXAMPLE / f"{name}.json").read_text(encoding="utf-8"))


def write_case(tmp_path, u, g, m):
    for name, rec in (("unspoiled", u), ("ground_truth", g), ("manifest", m)):
        (tmp_path / f"{name}.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    return [p for p in validate_dir(tmp_path, allow_synthetic=True) if p.level == "ERROR"]


@pytest.fixture
def case():
    return load("unspoiled"), load("ground_truth"), load("manifest")


def test_example_is_valid():
    errors = [p for p in validate_dir(EXAMPLE, allow_synthetic=True) if p.level == "ERROR"]
    assert errors == []


def test_synthetic_template_rejected_in_real_db():
    assert any("synthetic" in p.message for p in validate_dir(EXAMPLE))


# ---- single-record schema rules ----

def test_undeclared_token_rejected(case):
    u = copy.deepcopy(case[0])
    u["chronology"][0]["event"] += " with [MYSTERY_PARTY]"
    with pytest.raises(ValidationError, match="MYSTERY_PARTY"):
        PublicUnspoiled.model_validate(u)


def test_ground_pointing_to_unknown_issue_rejected(case):
    u = copy.deepcopy(case[0])
    u["appellant_grounds"][0]["issue"] = "I9"
    with pytest.raises(ValidationError, match="unknown issue"):
        PublicUnspoiled.model_validate(u)


def test_conflict_needs_two_values(case):
    u = copy.deepcopy(case[0])
    u["typed_facts"]["date_of_default"] = {"values": ["2015-12-31"], "conflict": True, "src": [{"page": 2}]}
    with pytest.raises(ValidationError, match="conflict"):
        PublicUnspoiled.model_validate(u)


def test_fy_event_needs_range(case):
    u = copy.deepcopy(case[0])
    del u["chronology"][6]["date_to"]
    with pytest.raises(ValidationError, match="date_to"):
        PublicUnspoiled.model_validate(u)


def test_dismissed_cannot_be_appellant_win(case):
    g = copy.deepcopy(case[1])
    g["appellant_won"] = True
    with pytest.raises(ValidationError, match="DISMISSED"):
        PublicGroundTruth.model_validate(g)


def test_unknown_field_rejected(case):
    m = copy.deepcopy(case[2])
    m["judge_notes"] = "x"
    with pytest.raises(ValidationError):
        PublicManifest.model_validate(m)


# ---- cross-file rules ----

@pytest.mark.parametrize("mutate, expect", [
    (lambda u, g, m: g["issue_findings"].pop(), "has 0 findings"),
    (lambda u, g, m: u.update(law_as_of="2021-03-15"), "law_as_of"),
    (lambda u, g, m: m.update(split="test"), "split"),
    (lambda u, g, m: u["impugned_order"].update(reasoning_summary="Synthetic Bank Name lent money"), "manifest.real"),
    (lambda u, g, m: u["record_documents"][0].update(gist="see CP No. 123 of 2020"), "case/application number"),
    (lambda u, g, m: u["issues"][0].update(text="Whether the NCLT rightly admitted the application."), "not neutral"),
    (lambda u, g, m: u["record_documents"][1].update(
        gist="a signed balance sheet entry made before limitation expires can extend limitation"), "gram"),
    (lambda u, g, m: u["chronology"][0]["src"][0].update(page=99), "src page"),
    (lambda u, g, m: u.update(proceeding_type="COMPANIES_ACT_241_242"), "not IBC"),
])
def test_cross_file_rules(tmp_path, case, mutate, expect):
    u, g, m = (copy.deepcopy(x) for x in case)
    mutate(u, g, m)
    errors = write_case(tmp_path, u, g, m)
    assert any(expect in p.message for p in errors), [str(p) for p in errors]


def test_connected_appeals_must_be_one_case(tmp_path, case):
    u, g, m = case
    u2, g2, m2 = (dict(copy.deepcopy(x), case_uid="PC-TEMPLATE2") for x in case)
    for name, recs in (("unspoiled", [u, u2]), ("ground_truth", [g, g2]), ("manifest", [m, m2])):
        (tmp_path / f"{name}.jsonl").write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")
    errors = validate_dir(tmp_path, allow_synthetic=True)
    assert any("connected appeals" in p.message for p in errors)


def test_exported_schemas_are_current():
    for name, model in (("unspoiled", PublicUnspoiled), ("ground_truth", PublicGroundTruth), ("manifest", PublicManifest)):
        on_disk = json.loads((EXAMPLE.parent / f"{name}.schema.json").read_text(encoding="utf-8"))
        assert on_disk == model.model_json_schema(), f"run scripts/export_schemas.py ({name})"
