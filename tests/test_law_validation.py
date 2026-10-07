"""Law DB validation report (BUILD_PLAN Step 2): every malformed, duplicate or dangling record is listed.

Inputs are synthetic records written to a temporary folder; the statute IDs are placeholders, not law.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lexarena.ingest.law_db import content_hash, read_law_sources, snapshot_id, validate_law_db


def law_record(statute_id: str, **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "_id": statute_id,
        "statute_id": statute_id,
        "act_name": "<act>",
        "section_number": "<n>",
        "section_title": "<title>",
        "jurisdiction_type": "<TYPE>",
        "forum_level": "<FORUM>",
        "statutory_summary": "<summary>",
        "core_judicial_inquiry": "<inquiry>",
        "intersecting_statute_ids": [],
        "diagnostic_checklist": {
            "applicant_eligibility": [],
            "financial_threshold": {"minimum_amount": None, "currency": None},
            "mandatory_prerequisites": [],
            "statutory_bars": [],
            "saving_exceptions": [],
        },
        "procedural_timelines": {"adjudication_window_days": None, "rectification_window_days": None},
        "audit_error_codes": ["ERR_PLACEHOLDER"],
    }
    record.update(overrides)
    return record


def write(folder: Path, name: str, records: list[dict[str, Any]] | str) -> None:
    text = records if isinstance(records, str) else json.dumps(records, indent=2)
    (folder / name).write_text(text, encoding="utf-8")


def test_clean_source_is_fully_valid(tmp_path: Path) -> None:
    write(tmp_path, "a.json", [law_record("TEST_ACT_SEC_1", intersecting_statute_ids=["TEST_ACT_SEC_2"])])
    write(tmp_path, "b.json", [law_record("TEST_ACT_SEC_2")])
    report = validate_law_db(*read_law_sources(tmp_path))
    assert (report.records_read, report.valid, report.loadable) == (2, 2, True)
    assert (report.malformed, report.duplicates, report.dangling_intersecting) == ([], [], [])
    assert sorted(report.records) == ["TEST_ACT_SEC_1", "TEST_ACT_SEC_2"]


def test_malformed_record_is_listed_with_location(tmp_path: Path) -> None:
    broken = law_record("TEST_ACT_SEC_1")
    del broken["core_judicial_inquiry"]
    broken["procedural_timelines"]["adjudication_window_days"] = "14"
    write(tmp_path, "a.json", [law_record("TEST_ACT_SEC_0"), broken])
    report = validate_law_db(*read_law_sources(tmp_path))
    assert report.valid == 1 and not report.loadable
    [bad] = report.malformed
    assert (bad.file, bad.index, bad.statute_id) == ("a.json", 1, "TEST_ACT_SEC_1")
    assert any("core_judicial_inquiry" in e for e in bad.errors)
    assert any("adjudication_window_days" in e for e in bad.errors)


def test_parse_error_is_listed_and_blocks_loading(tmp_path: Path) -> None:
    write(tmp_path, "a.json", '[{"_id": "TEST_ACT_SEC_1",, }]')
    report = validate_law_db(*read_law_sources(tmp_path))
    assert report.parse_errors and not report.loadable


def test_duplicate_ids_are_listed_and_block_loading(tmp_path: Path) -> None:
    write(tmp_path, "a.json", [law_record("TEST_ACT_SEC_1")])
    write(tmp_path, "b.json", [law_record("TEST_ACT_SEC_1", section_title="<other>")])
    report = validate_law_db(*read_law_sources(tmp_path))
    assert [d.statute_id for d in report.duplicates] == ["TEST_ACT_SEC_1"]
    assert report.duplicates[0].files == ["a.json", "b.json"]
    assert not report.loadable


def test_dangling_reference_is_listed_with_suggestions(tmp_path: Path) -> None:
    refs = ["TEST_SEC_7", "TEST_ACT_2001_SEC_7_SUB_2", "OTHER_ACT_SEC_9", "TEST_ACT_2001_SEC_7"]
    write(
        tmp_path,
        "a.json",
        [law_record("TEST_ACT_2001_SEC_7"), law_record("TEST_ACT_2001_SEC_8", intersecting_statute_ids=refs)],
    )
    report = validate_law_db(*read_law_sources(tmp_path))
    found = {d.missing_id: d.suggestions for d in report.dangling_intersecting}
    assert found == {
        "TEST_SEC_7": ["TEST_ACT_2001_SEC_7"],  # another spelling of an existing ID
        "TEST_ACT_2001_SEC_7_SUB_2": ["TEST_ACT_2001_SEC_7"],  # a sub-section of an existing ID
        "OTHER_ACT_SEC_9": [],  # nothing in the DB
    }
    assert all(d.referenced_by == ["TEST_ACT_2001_SEC_8"] for d in report.dangling_intersecting)
    assert report.loadable  # dangling references are reported, not blocking


def test_suggestions_never_match_a_different_section_number(tmp_path: Path) -> None:
    write(
        tmp_path,
        "a.json",
        [law_record("TEST_ACT_SEC_2"), law_record("TEST_ACT_SEC_21", intersecting_statute_ids=["TEST_SEC_211"])],
    )
    report = validate_law_db(*read_law_sources(tmp_path))
    assert report.dangling_intersecting[0].suggestions == []


def test_error_code_and_reference_hygiene(tmp_path: Path) -> None:
    write(
        tmp_path,
        "a.json",
        [
            law_record("TEST_ACT_SEC_1", audit_error_codes=[]),
            law_record("TEST_ACT_SEC_2", audit_error_codes=["err lower", "ERR_X", "ERR_X"]),
            law_record("TEST_ACT_SEC_3", intersecting_statute_ids=["TEST_ACT_SEC_3"]),
        ],
    )
    report = validate_law_db(*read_law_sources(tmp_path))
    issues = {(i.statute_id, i.issue) for i in report.record_issues}
    assert ("TEST_ACT_SEC_1", "no audit_error_codes") in issues
    assert ("TEST_ACT_SEC_2", "audit_error_code not an uppercase tag: 'err lower'") in issues
    assert ("TEST_ACT_SEC_2", "audit_error_code repeated: 'ERR_X'") in issues
    assert ("TEST_ACT_SEC_3", "lists itself in intersecting_statute_ids") in issues
    assert report.loadable  # hygiene issues are reported, not blocking


def test_undocumented_fields_are_reported(tmp_path: Path) -> None:
    record = law_record("TEST_ACT_SEC_1")
    record["diagnostic_checklist"]["zz_probe"] = "<x>"
    write(tmp_path, "a.json", [record])
    report = validate_law_db(*read_law_sources(tmp_path))
    assert report.undocumented_fields == {"diagnostic_checklist.zz_probe": ["TEST_ACT_SEC_1"]}


def test_content_hash_ignores_key_order_and_snapshot_tracks_every_record() -> None:
    a = law_record("TEST_ACT_SEC_1")
    reordered = dict(reversed(list(a.items())))
    assert content_hash(a) == content_hash(reordered)
    b = law_record("TEST_ACT_SEC_2")
    snap = snapshot_id({"TEST_ACT_SEC_1": content_hash(a), "TEST_ACT_SEC_2": content_hash(b)})
    assert snap == snapshot_id({"TEST_ACT_SEC_2": content_hash(b), "TEST_ACT_SEC_1": content_hash(a)})
    changed = law_record("TEST_ACT_SEC_2", section_title="<changed>")
    assert snap != snapshot_id({"TEST_ACT_SEC_1": content_hash(a), "TEST_ACT_SEC_2": content_hash(changed)})
