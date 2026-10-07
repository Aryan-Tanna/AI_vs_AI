"""Preparing precedent records for Qdrant (BUILD_PLAN Step 4, DATA_FORMATS §2). Synthetic placeholder records;
the parsing follows the documented format (numbered labelled sections), never particular records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lexarena.ingest.precedents import DERIVED_FIELDS, prepare_precedents, read_precedent_sources
from lexarena.precedent_text import facts_sections, ratio_text
from lexarena.statute_ids import normalize_statutes
from tests.fakes import WordEmbedder


def precedent(pid: str, **change: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "precedent_id": pid,
        "case_title": "<A vs B>",
        "appeal_number": "<appeal>",
        "forum": "NCLAT",
        "bench": "<bench>",
        "decision_date": "2001-02-03",
        "final_order": "DISMISSED",
        "is_overruled": False,
        "statutes_cited": ["TEST_ACT_SEC_7"],
        "material_facts": "1. PARTY IDENTITIES: <parties> 2. COMMERCIAL TRANSACTION: <deal> "
        "3. DEFAULT METRICS: <default>",
        "legal_issues": "1. <issue>",
        "ratio_decidendi": "1. ABSTRACT LEGAL RULE: <rule> 2. STATUTORY INTERPRETATION: <reading> "
        "3. EVIDENTIARY TEST APPLIED: <test> 4. DEFINITIVE CONCLUSION: <outcome>",
        "operative_order": "<order>",
        "summary": "<summary>",
    }
    return {**base, **change}


def write_jsonl(folder: Path, name: str, records: list[dict[str, Any]]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


KNOWN = {"TEST_ACT_SEC_7", "TEST_ACT_2001_SEC_9", "TEST_ACT_SEC_29A"}


def test_facts_sections_skip_party_identities() -> None:
    sections = facts_sections(precedent("P1")["material_facts"])
    assert sections == ["COMMERCIAL TRANSACTION: <deal>", "DEFAULT METRICS: <default>"]


def test_facts_without_numbered_sections_are_one_section() -> None:
    assert facts_sections("<free text with no headings>") == ["<free text with no headings>"]


def test_ratio_uses_parts_one_to_three_only() -> None:
    text = ratio_text(precedent("P1")["ratio_decidendi"])
    assert "<rule>" in text and "<reading>" in text and "<test>" in text and "<outcome>" not in text


def test_statutes_normalize_to_section_level_ids() -> None:
    found, unresolved = normalize_statutes(
        ["TEST_ACT_SEC_7", "TEST_ACT_SEC_29A_C", "TEST_SEC_9", "OTHER_ACT_SEC_1", "TEST_ACT_SEC_7"], KNOWN
    )
    assert found == ["TEST_ACT_SEC_7", "TEST_ACT_SEC_29A", "TEST_ACT_2001_SEC_9"]
    assert unresolved == ["OTHER_ACT_SEC_1"]


def test_bracketed_sub_sections_resolve_to_the_section() -> None:
    found, unresolved = normalize_statutes(["TEST_ACT_SEC_7(5)", "TEST_ACT_SEC_7(1)(a)", "TEST_ACT_SEC_77(2)"], KNOWN)
    assert found == ["TEST_ACT_SEC_7"] and unresolved == ["TEST_ACT_SEC_77(2)"]


def test_prepare_derives_fields_without_touching_the_record(tmp_path: Path) -> None:
    write_jsonl(tmp_path, "a.jsonl", [precedent("P1")])
    prepared = prepare_precedents(*read_precedent_sources(tmp_path), KNOWN, WordEmbedder(), window_tokens=50)
    [p] = prepared.points
    assert {k: v for k, v in p.payload.items() if k not in DERIVED_FIELDS} == precedent("P1")
    assert p.payload["decision_date_ts"] == "2001-02-03T00:00:00Z"
    assert len(p.facts_texts) == 2 and p.ratio_text


def test_identical_copies_collapse_and_colliding_ids_stay_apart(tmp_path: Path) -> None:
    same = precedent("P1")
    other_case = precedent("P1", case_title="<C vs D>", decision_date="2002-01-01")
    write_jsonl(tmp_path, "a.jsonl", [same, same, other_case])
    prepared = prepare_precedents(*read_precedent_sources(tmp_path), KNOWN, WordEmbedder(), window_tokens=50)
    assert len(prepared.points) == 2
    assert prepared.report.exact_duplicates == 1
    assert prepared.report.ambiguous_precedent_ids == {"P1": 2}
    assert len({p.point_id for p in prepared.points}) == 2


def test_conflicting_copies_of_one_case_are_reported(tmp_path: Path) -> None:
    write_jsonl(tmp_path, "a.jsonl", [precedent("P1"), precedent("P1", summary="<different>")])
    prepared = prepare_precedents(*read_precedent_sources(tmp_path), KNOWN, WordEmbedder(), window_tokens=50)
    assert len(prepared.points) == 1
    assert [c.precedent_uid for c in prepared.report.conflicting_copies] == [prepared.points[0].precedent_uid]


def test_malformed_and_undated_records_are_reported_not_loaded(tmp_path: Path) -> None:
    bad = precedent("P2")
    del bad["summary"]
    write_jsonl(tmp_path, "a.jsonl", [precedent("P1"), bad, precedent("P3", decision_date="<no date>")])
    prepared = prepare_precedents(*read_precedent_sources(tmp_path), KNOWN, WordEmbedder(), window_tokens=50)
    assert [p.payload["precedent_id"] for p in prepared.points] == ["P1"]
    assert [m.precedent_id for m in prepared.report.malformed] == ["P2"]
    assert prepared.report.undated == ["P3"]


def test_long_sections_are_split_into_windows(tmp_path: Path) -> None:
    long_section = " ".join(f"w{i}" for i in range(120))
    rec = precedent("P1", material_facts=f"1. PARTY IDENTITIES: <x> 2. COMMERCIAL TRANSACTION: {long_section}")
    write_jsonl(tmp_path, "a.jsonl", [rec])
    prepared = prepare_precedents(*read_precedent_sources(tmp_path), KNOWN, WordEmbedder(), window_tokens=50)
    [p] = prepared.points
    assert len(p.facts_texts) == 3  # 122 words in windows of at most 50 tokens
    assert all(WordEmbedder().count_tokens(t) <= 50 for t in p.facts_texts)
    assert prepared.report.windowed_sections == 1
