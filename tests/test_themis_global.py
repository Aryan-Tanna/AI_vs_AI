"""THEMIS-GLOBAL (BUILD_PLAN Step 10; SPEC E3, E5, I3-1; D-076): a planted contradiction is found, the model is held
to the transcript, and the report holds nothing from ground truth."""

from __future__ import annotations

import json
from typing import Any

from lexarena.prompts import PromptStore
from lexarena.schemas.transcript import PublishedTurn
from lexarena.themis_global.audit import TranscriptAudit, audit_transcript, build_report, confirmed
from tests import builders
from tests.conftest import PROMPTS_ROOT
from tests.judge_fixtures import CASE_ID, CFG, SESSION_ID, agent_view, client

TEXTS = {
    1: "The debt was acknowledged in writing on two occasions before limitation expired.",
    2: "No acknowledgment was ever given; the letters were mere offers of settlement.",
    3: "The settlement letters are acknowledgments. Separately, the application was filed in time.",
    4: "Even if acknowledged, the claim was time barred when filed.",
    5: "Petitioner closes: the debt was never acknowledged at all.",
    6: "Respondent closes: the letters were offers, not acknowledgments.",
}
TYPES = {1: "OPENING", 2: "OPENING", 3: "REBUTTAL", 4: "REBUTTAL", 5: "CLOSING", 6: "CLOSING"}


def turns() -> list[PublishedTurn]:
    out = []
    for n, text in TEXTS.items():
        side = "PETITIONER" if n % 2 else "RESPONDENT"
        doc = builders.published_turn(SESSION_ID, CASE_ID, n, side).to_document()  # type: ignore[arg-type]
        doc |= {"published_text": text, "turn_type": TYPES[n]}
        doc["claims"][0] |= {"claim_id": f"T{n:02d}-C1", "text": text}
        out.append(PublishedTurn.model_validate(doc))
    return out


def point(turn: int, speaker: str, quote: str, status: str = "ANSWERED", centrality: int = 2) -> dict[str, Any]:
    return {
        "turn": turn,
        "speaker": speaker,
        "issue_id": "I1",
        "summary": "<summary>",
        "quote": quote,
        "centrality": centrality,
        "status": status,
        "answered_in_turn": None,
    }


def contradiction(speaker: str, a: str, b: str) -> dict[str, Any]:
    return {"speaker": speaker, "claim_a": a, "claim_b": b, "explanation": "<why>"}


def audit(points: list[dict[str, Any]], contradictions: list[dict[str, Any]]) -> TranscriptAudit:
    return TranscriptAudit.model_validate({"points": points, "contradictions": contradictions})


def test_points_must_quote_their_own_turn_and_be_answerable() -> None:
    ts = turns()
    kept, _ = confirmed(
        audit(
            [
                point(1, "PETITIONER", "acknowledged in writing"),  # kept
                point(1, "PETITIONER", "words nobody said"),  # not verbatim
                point(2, "PETITIONER", "mere offers of settlement"),  # wrong speaker for turn 2
                point(4, "RESPONDENT", "time barred when filed"),  # answerable by the petitioner's closing
                point(5, "PETITIONER", "never acknowledged at all"),  # a closing: nothing answers it
            ],
            [],
        ),
        ts,
    )
    assert [(p.turn, p.quote) for p in kept] == [(1, "acknowledged in writing"), (4, "time barred when filed")]


def test_a_planted_contradiction_is_found_and_bad_pairs_are_dropped() -> None:
    _, found = confirmed(
        audit(
            [],
            [
                contradiction("PETITIONER", "T01-C1", "T05-C1"),  # planted: acknowledged vs never acknowledged
                contradiction("PETITIONER", "T01-C1", "T02-C1"),  # crosses sides
                contradiction("PETITIONER", "T01-C1", "T01-C1"),  # same turn
                contradiction("RESPONDENT", "T02-C1", "T99-C1"),  # unknown claim
            ],
        ),
        turns(),
    )
    assert [(c.claim_a, c.claim_b) for c in found] == [("T01-C1", "T05-C1")]


def test_rebuttal_depth_and_consistency_per_side() -> None:
    ts = turns()
    points, contradictions = confirmed(
        audit(
            [
                point(1, "PETITIONER", "acknowledged in writing", "ANSWERED", 3),
                point(3, "PETITIONER", "filed in time", "IGNORED", 1),
                point(2, "RESPONDENT", "mere offers of settlement", "CONCEDED", 2),
            ],
            [contradiction("PETITIONER", "T01-C1", "T05-C1")],
        ),
        ts,
    )
    report = build_report(points, contradictions, ts)
    r = report.rebuttal_depth
    assert r["RESPONDENT"]["depth"] == 0.75  # answered 3 of 4 centrality-weighted petitioner points
    assert r["PETITIONER"]["depth"] == 0.0 and r["PETITIONER"]["conceded"] == 1
    assert report.consistency["PETITIONER"] == {"score": 1 - 1 / 3, "claims": 3, "contradictions": 1}
    assert report.consistency["RESPONDENT"]["score"] == 1.0


def test_the_audit_reads_only_the_transcript_and_reports_no_sealed_values() -> None:
    sentinel = "SENTINEL_GROUND_TRUTH"
    answer = {
        "points": [point(1, "PETITIONER", "acknowledged in writing")],
        "contradictions": [contradiction("PETITIONER", "T01-C1", "T05-C1")],
    }
    llm, auditor, _ = client([json.dumps(answer)])
    report = audit_transcript(llm, PromptStore(PROMPTS_ROOT), CFG, agent_view(), turns(), session_id=SESSION_ID)
    sent = auditor.requests[0].messages[-1].content
    assert TEXTS[3] in sent and "[T03-C1]" in sent and auditor.requests[0].model.name == CFG.models.auditor.name
    assert sentinel not in json.dumps(report.model_dump())
    assert set(report.model_dump()) == {"consistency", "rebuttal_depth", "contradictions"}
    assert report.contradictions[0]["claim_b"] == "T05-C1"
