"""Assembling the sealed ground truth (BUILD_PLAN Step 6, SPEC H2, D-056). It must line up with the agent view:
same issue IDs, reliefs the agents were shown, real paragraphs. Placeholder content only (non-negotiable 1)."""

from __future__ import annotations

from datetime import date
from typing import Any

from lexarena.clerk.assemble import build_ground_truth, evidence_dependency
from lexarena.schemas.clerk import GroundTruthDraft
from lexarena.schemas.statute_alias import StatuteAliasTable

PARAS = {"P1", "P2", "P3"}
ISSUES = {"I1"}
RELIEFS = {"PETITIONER": ["<relief p>"], "RESPONDENT": ["<relief r>"]}


def gt_draft(**change: Any) -> GroundTruthDraft:
    base: dict[str, Any] = {
        "citation": {
            "case_number": "<number>",
            "arising_from": None,
            "bench": ["<member>"],
            "decision_date": "2002-01-01",
            "source_title": "<title>",
        },
        "real_submissions": {
            "PETITIONER": [
                {
                    "issue_id": "I1",
                    "contention": "<contention>",
                    "statutes_cited": ["TEST_ACT_SEC_7"],
                    "authorities_cited": [],
                    "source_paras": ["P2"],
                }
            ],
            "RESPONDENT": [],
        },
        "statutory_analysis": [],
        "precedent_analysis": [],
        "issue_findings": [
            {
                "issue_id": "I1",
                "favours": "RESPONDENT",
                "driver": "LAW",
                "finding": "<finding>",
                "reasoning": "<reasoning>",
                "test_applied": "<test>",
                "decisive_points": [],
                "authorities_relied_on": [],
                "source_paras": ["P3"],
            }
        ],
        "conclusion": {
            "disposition": "DISMISSED",
            "reliefs": [{"relief": "<relief p>", "sought_by": "PETITIONER", "outcome": "REFUSED"}],
            "directions": [],
            "costs": None,
            "overall_favours": "RESPONDENT",
        },
    }
    base.update(change)
    return GroundTruthDraft.model_validate(base)


def build(d: GroundTruthDraft, decided: date = date(2002, 1, 1)) -> Any:
    return build_ground_truth(
        d,
        case_id="CASE-T",
        anonymization_map={"Company-B": "<real name>"},
        issue_ids=ISSUES,
        reliefs=RELIEFS,
        paragraph_ids=PARAS,
        known_statutes={"TEST_ACT_SEC_7"},
        aliases=StatuteAliasTable(aliases=[]),
        expected_decision_date=decided,
    )


def test_a_consistent_draft_becomes_sealed_ground_truth() -> None:
    result = build(gt_draft())
    assert result.problems == []
    assert result.truth.id == "CASE-T" and result.truth.access == "SEALED_UNTIL_VERDICT"
    assert result.truth.anonymization_map == {"Company-B": "<real name>"}


def test_a_finding_for_an_unknown_issue_or_a_missing_finding_blocks() -> None:
    d = gt_draft()
    d.issue_findings[0].issue_id = "I7"
    problems = build(d).problems
    assert any("I7" in p for p in problems) and any("I1" in p and "no finding" in p for p in problems)


def test_a_relief_the_agents_never_saw_blocks() -> None:
    d = gt_draft()
    d.conclusion.reliefs[0].relief = "<another relief>"
    assert any("<another relief>" in p for p in build(d).problems)


def test_a_source_that_is_not_a_paragraph_blocks() -> None:
    d = gt_draft()
    d.issue_findings[0].source_paras = ["P99"]
    assert any("P99" in p for p in build(d).problems)


def test_a_decision_date_that_disagrees_with_the_manifest_blocks() -> None:
    assert any("decision date" in p for p in build(gt_draft(), decided=date(2003, 3, 3)).problems)


def test_statutes_resolve_or_are_flagged() -> None:
    d = gt_draft()
    d.real_submissions.PETITIONER[0].statutes_cited = ["TEST_ACT_SEC_7(2)", "<UNKNOWN_SEC_1>"]
    result = build(d)
    assert result.truth.real_submissions.PETITIONER[0].statutes_cited == ["TEST_ACT_SEC_7"]
    assert [f.code for f in result.flags] == ["STATUTE_NOT_IN_LAW_DB"]


def test_evidence_dependency_follows_the_drivers() -> None:
    assert evidence_dependency(["LAW", "LAW"]) == "LAW_ONLY"
    assert evidence_dependency(["EVIDENCE"]) == "EVIDENCE_DECIDED"
    assert evidence_dependency(["LAW", "EVIDENCE"]) == "MIXED"
    assert evidence_dependency(["MIXED"]) == "MIXED"
