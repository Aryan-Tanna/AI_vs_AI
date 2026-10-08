"""THEMIS-GLOBAL: the whole-transcript audit before judging (BUILD_PLAN Step 10; SPEC E3, E5, I3-1; D-076).

Reads only the published transcript and the framed issues; it never sees ground truth (it holds no sealed handle and
the import boundary forbids one). One auditor call lists each side's points and its self-contradictions; code then
holds the model to the transcript:
- a point counts only if its quote is verbatim in the turn it is attributed to, by that turn's speaker;
- a point is answerable only if the other side spoke after it; the parallel closings answer nothing after them;
- a contradiction counts only between two existing claim IDs of the same side from different turns.

Rebuttal depth (E3) for a side is the centrality-weighted share of the other side's answerable points it ANSWERED
(concessions are counted apart). Consistency (E5) is 1 minus the side's confirmed contradictions per claim.

The report is stored with the session and used by reflection and the run reports. It is not shown to the judges: a
verifier's assessment would anchor them (SPEC E1).
"""

from __future__ import annotations

import re
from typing import Literal

from lexarena.llm.client import LLMClient
from lexarena.prompts import PromptStore
from lexarena.schemas.base import SIDES, Side, StoredModel
from lexarena.schemas.case import AgentCaseView
from lexarena.schemas.config import AppConfig
from lexarena.schemas.session import ThemisGlobalReport
from lexarena.schemas.transcript import PublishedTurn

ROLE = "auditor"
CLOSING = "CLOSING"  # the turn type of the parallel closings (orchestrator schedule)
COUNSEL = {"PETITIONER": "Petitioner's counsel", "RESPONDENT": "Respondent's counsel"}


class AuditPoint(StoredModel):
    turn: int
    speaker: Side
    issue_id: str | None
    summary: str
    quote: str
    centrality: Literal[1, 2, 3]  # literal-ok: the 1-3 scale the audit prompt defines
    status: Literal["ANSWERED", "CONCEDED", "IGNORED"]
    answered_in_turn: int | None


class AuditContradiction(StoredModel):
    speaker: Side
    claim_a: str
    claim_b: str
    explanation: str


class TranscriptAudit(StoredModel):
    points: list[AuditPoint]
    contradictions: list[AuditContradiction]


def _squeeze(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def render_transcript(turns: list[PublishedTurn]) -> str:
    blocks = []
    for t in turns:
        lines = [f"TURN {t.turn} ({t.turn_type}) {COUNSEL[t.speaker]}", t.published_text]
        lines += [f"  [{c.claim_id}] {c.type}: {c.text} (record {', '.join(c.record_ids) or '-'})" for c in t.claims]
        lines += [f"  VERIFIER FLAG {f.code}" for f in t.visible_flags]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _answerable(point: AuditPoint, turns: list[PublishedTurn]) -> bool:
    """The other side spoke after this point and saw it: a closing (written in parallel) answers nothing."""
    origin = next((t for t in turns if t.turn == point.turn), None)
    if origin is None or origin.turn_type == CLOSING:
        return False
    return any(t.speaker != point.speaker and t.turn > point.turn for t in turns)


def confirmed(audit: TranscriptAudit, turns: list[PublishedTurn]) -> tuple[list[AuditPoint], list[AuditContradiction]]:
    by_turn = {t.turn: t for t in turns}
    claim_owner = {c.claim_id: (t.speaker, t.turn) for t in turns for c in t.claims}
    points = [
        p
        for p in audit.points
        if p.turn in by_turn
        and by_turn[p.turn].speaker == p.speaker
        and p.quote.strip()
        and _squeeze(p.quote) in _squeeze(by_turn[p.turn].published_text)
        and _answerable(p, turns)
    ]
    contradictions = [
        c
        for c in audit.contradictions
        if c.claim_a in claim_owner
        and c.claim_b in claim_owner
        and claim_owner[c.claim_a][0] == c.speaker == claim_owner[c.claim_b][0]
        and claim_owner[c.claim_a][1] != claim_owner[c.claim_b][1]
    ]
    return points, contradictions


def build_report(
    points: list[AuditPoint], contradictions: list[AuditContradiction], turns: list[PublishedTurn]
) -> ThemisGlobalReport:
    rebuttal: dict[str, object] = {}
    consistency: dict[str, object] = {}
    for side in SIDES:
        theirs = [p for p in points if p.speaker != side]
        weight = sum(p.centrality for p in theirs)
        answered = sum(p.centrality for p in theirs if p.status == "ANSWERED")
        rebuttal[side] = {
            "depth": answered / weight if weight else None,
            "opponent_points": len(theirs),
            "answered": sum(p.status == "ANSWERED" for p in theirs),
            "conceded": sum(p.status == "CONCEDED" for p in theirs),
            "ignored": sum(p.status == "IGNORED" for p in theirs),
        }
        claims = sum(len(t.claims) for t in turns if t.speaker == side)
        own = sum(c.speaker == side for c in contradictions)
        consistency[side] = {
            "score": 1 - min(1.0, own / claims) if claims else None,
            "claims": claims,
            "contradictions": own,
        }
    rebuttal["points"] = [p.model_dump() for p in points]
    return ThemisGlobalReport(
        consistency=consistency, rebuttal_depth=rebuttal, contradictions=[c.model_dump() for c in contradictions]
    )


def audit_transcript(
    llm: LLMClient,
    prompts: PromptStore,
    cfg: AppConfig,
    case: AgentCaseView,
    turns: list[PublishedTurn],
    *,
    session_id: str,
) -> ThemisGlobalReport:
    ref = cfg.prompts.themis_global_audit
    issues = "\n".join(f"[{i.issue_id}] {i.question}" for i in case.framed_issues)
    prompt = prompts.render(ref.id, ref.version, issues=issues, transcript=render_transcript(turns))
    audit = llm.complete_json(role=ROLE, user=prompt, schema=TranscriptAudit, session_id=session_id).value
    points, contradictions = confirmed(audit, turns)
    return build_report(points, contradictions, turns)
