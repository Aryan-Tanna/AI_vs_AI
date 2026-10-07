"""Builders for structurally valid documents used in tests.

All text is an obvious placeholder (`<...>`) or a sentinel marker, never a fact from or about a real case
(non-negotiable 1). Sentinels let access-control tests prove a sealed value never reaches a reader.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from lexarena.schemas.base import Side
from lexarena.schemas.case import Case
from lexarena.schemas.ground_truth import CaseGroundTruth
from lexarena.schemas.retrieval import CaseScope
from lexarena.schemas.session import Session
from lexarena.schemas.transcript import PrivateTurnData, PublishedTurn, turn_document_id

PLACEHOLDER_DATE = "2000-01-01"  # literal-ok: arbitrary placeholder, not a case date
SCOPE = CaseScope.model_validate({"decided_before": PLACEHOLDER_DATE, "excluded_precedent_ids": ["<excluded>"]})


def case_doc(case_id: str, *, build_marker: str = "<build>", date_marker: str = PLACEHOLDER_DATE) -> dict[str, Any]:
    return {
        "_id": case_id,
        "split": "DEV",
        "build": {
            "source_forum": "NCLAT",
            "evidence_dependency": "LAW_ONLY",
            "issues_source": "FRAMED_BY_COURT",
            "memorization_probe": "NOT_IDENTIFIED",
            "excluded_precedent_ids": [build_marker],
            "extraction_flags": [],
            "human_reviewed": False,
            "clerk_version": "<clerk version>",
        },
        "agent_view": {
            "metadata": {
                "forum": "NCLAT",
                "proceeding_type": "APPEAL_UNDER_SEC_61",
                "statutes_invoked": ["<statute id>"],
                "simulation_date": date_marker,
                "key_dates": [{"label": "FILING", "date": PLACEHOLDER_DATE, "fact_id": "F1"}],
            },
            "parties": [
                {
                    "party_id": "A1",
                    "pseudonym": "<pseudonym A>",
                    "status": "FINANCIAL_CREDITOR",
                    "simulation_side": "PETITIONER",
                    "appeal_position": "APPELLANT",
                    "represented_by_agent": "LEX_P",
                    "substituted_from": None,
                },
                {
                    "party_id": "R1",
                    "pseudonym": "<pseudonym B>",
                    "status": "CORPORATE_DEBTOR",
                    "simulation_side": "RESPONDENT",
                    "appeal_position": "RESPONDENT_1",
                    "represented_by_agent": "LEX_D",
                    "substituted_from": None,
                },
            ],
            "factual_background": "<background> [F1]",
            "record": {
                "stipulated_facts": [{"fact_id": "F1", "text": "<fact>", "source_paras": ["1"]}],
                "contested_facts": [
                    {
                        "fact_id": "C1",
                        "question": "<question>",
                        "petitioner_version": "<version P>",
                        "respondent_version": "<version R>",
                        "source_paras": ["2"],
                    }
                ],
                "exhibits": [
                    {
                        "exhibit_id": "EX-1",
                        "title": "<title>",
                        "filed_by": "A1",
                        "known_contents": ["<content>"],
                        "contents_beyond_known": "UNKNOWN",
                        "authenticity": "PRESUMED",
                        "source_paras": ["3"],
                    }
                ],
                "amounts": [
                    {
                        "amount_id": "AM1",
                        "label": "CLAIMED_DEFAULT",
                        "value_inr": 1,
                        "date": None,
                        "party_id": "A1",
                        "fact_id": "F1",
                    }
                ],
            },
            "procedural_history": [
                {"step": 1, "date": PLACEHOLDER_DATE, "forum": "<forum>", "event": "<event>", "fact_id": "F1"}
            ],
            "lower_forum_order": {
                "exists": True,
                "forum": "NCLT",
                "result": "DISMISSED",
                "directions": ["<direction>"],
                "reasons_summary": "<reasons>",
                "ex_parte": False,
            },
            "framed_issues": [
                {"issue_id": "I1", "question": "<question>", "statutes": ["<statute id>"], "raised_by": "COURT"}
            ],
            "reliefs_sought": {"PETITIONER": ["<relief P>"], "RESPONDENT": ["<relief R>"]},
            "opening_positions": {
                "PETITIONER": [{"issue_id": "I1", "ground": "<ground P>"}],
                "RESPONDENT": [{"issue_id": "I1", "ground": "<ground R>"}],
            },
            "presumptions": ["<presumption>"],
        },
    }


def case(case_id: str, **kwargs: str) -> Case:
    return Case.model_validate(case_doc(case_id, **kwargs))


def ground_truth(case_id: str, sentinel: str) -> CaseGroundTruth:
    """Every free-text field carries the sentinel, so any leak of any field is detectable."""
    paras = ["1"]
    return CaseGroundTruth.model_validate(
        {
            "_id": case_id,
            "access": "SEALED_UNTIL_VERDICT",
            "citation": {
                "case_number": sentinel,
                "arising_from": None,
                "bench": [sentinel],
                "decision_date": PLACEHOLDER_DATE,
                "source_title": sentinel,
            },
            "anonymization_map": {"<pseudonym A>": sentinel},
            "real_submissions": {
                "PETITIONER": [
                    {
                        "issue_id": "I1",
                        "contention": sentinel,
                        "statutes_cited": [],
                        "authorities_cited": [],
                        "source_paras": paras,
                    }
                ],
                "RESPONDENT": [],
            },
            "statutory_analysis": [],
            "precedent_analysis": [],
            "issue_findings": [
                {
                    "issue_id": "I1",
                    "favours": "PETITIONER",
                    "driver": "LAW",
                    "finding": sentinel,
                    "reasoning": sentinel,
                    "test_applied": sentinel,
                    "decisive_points": [sentinel],
                    "authorities_relied_on": [],
                    "source_paras": paras,
                }
            ],
            "conclusion": {
                "disposition": "ALLOWED",
                "reliefs": [{"relief": "<relief P>", "sought_by": "PETITIONER", "outcome": "GRANTED"}],
                "directions": [sentinel],
                "costs": None,
                "overall_favours": "PETITIONER",
            },
        }
    )


def session(session_id: str, case_id: str) -> Session:
    return Session.model_validate(
        {
            "_id": session_id,
            "case_id": case_id,
            "split": "DEV",
            "state": "CREATED",
            "versions": {
                "git_sha": "<sha>",
                "config_version": "v1",
                "config_sha256": "<hash>",
                "law_db_snapshot": "<law>",
                "precedent_db_snapshot": "<precedents>",
                "memory_snapshot": "<memory>",
            },
            "config": {"lawyer_model": "<lawyer model>", "judge_model": "<judge model>", "seed": 0},
            "themis_global": None,
            "judge_scorecards": [],
            "aggregate": None,
            "winner": None,
            "evaluation": None,
            "lessons_written": [],
        }
    )


def published_turn(session_id: str, case_id: str, turn: int, speaker: Side) -> PublishedTurn:
    return PublishedTurn.model_validate(
        {
            "_id": turn_document_id(session_id, turn),
            "case_id": case_id,
            "session_id": session_id,
            "turn": turn,
            "speaker": speaker,
            "turn_type": "OPENING",
            "issues_addressed": ["I1"],
            "published_text": "<argument text>",
            "claims": [
                {
                    "claim_id": "C1",
                    "type": "FACT",
                    "text": "<claim>",
                    "record_ids": ["F1"],
                    "statute_id": None,
                    "precedent_ids": [],
                }
            ],
            "visible_flags": [],
            "created_at": datetime(2000, 1, 1, tzinfo=UTC).isoformat(),  # literal-ok: placeholder timestamp
        }
    )


def private_turn(session_id: str, case_id: str, turn: int, side: Side, sentinel: str) -> PrivateTurnData:
    return PrivateTurnData.model_validate(
        {
            "_id": turn_document_id(session_id, turn),
            "case_id": case_id,
            "session_id": session_id,
            "turn": turn,
            "side": side,
            "themis_local": {
                "outcome": "PASS_WITH_NOTES",
                "attempts": 1,
                "hard_errors_by_attempt": [[]],
                "warnings": [{"code": "WARN_PREREQUISITE_UNADDRESSED", "detail": sentinel}],
                "s_local": 0.5,
            },
            "claim_assessments": [{"claim_id": "C1", "citation_tier": None, "entailment": None}],
            "statute_checklists": [],
        }
    )
