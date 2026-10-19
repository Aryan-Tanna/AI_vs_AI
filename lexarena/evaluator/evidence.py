"""Whether the advocates had the evidence an evidence-decided issue turned on (D-151). After the verdict only.

SPEC F5 keeps issues the court decided on EVIDENCE out of the issue score and out of the lessons, because the agents
may never have had that evidence. But the record is built from the judgment, so the evidence often is in it (DEV_0013
I2, DEV_0014 I2: the bench decided both as the court did, and neither counted). For each EVIDENCE issue, the court's
decisive points are checked against the agent-visible record: the issue counts as "evidence in record" only when
every point is IN_RECORD with at least one record ID that exists in that record.

Sealed by construction: the decisive points come from the ground-truth repository, which refuses every read before
VERDICT_RECORDED; only a yes/no and record IDs leave this module, into the session's evaluation, which no agent,
THEMIS instance or judge reads. Nothing is written back to the case.
"""

from __future__ import annotations

from dataclasses import dataclass

from lexarena.llm.client import LLMClient
from lexarena.prompts import PromptStore
from lexarena.schemas.case import AgentCaseView
from lexarena.schemas.config import AppConfig
from lexarena.schemas.evaluation import EvidenceCheck
from lexarena.schemas.ground_truth import CaseGroundTruth
from lexarena.themis_local.layer2 import record_index, render_record

ROLE = "verifier"
EVIDENCE = "EVIDENCE"


@dataclass(frozen=True)
class EvidenceAvailability:
    in_record: bool
    record_ids: list[str]


def evidence_in_record(
    llm: LLMClient,
    prompts: PromptStore,
    cfg: AppConfig,
    case: AgentCaseView,
    truth: CaseGroundTruth,
    *,
    session_id: str,
) -> dict[str, EvidenceAvailability]:
    """One verdict per EVIDENCE issue; other issues are not asked about."""
    ref = cfg.prompts.evaluator_evidence
    record = render_record(case)
    known = set(record_index(case))
    out: dict[str, EvidenceAvailability] = {}
    for finding in truth.issue_findings:
        if finding.driver != EVIDENCE:
            continue
        points = finding.decisive_points
        prompt = prompts.render(
            ref.id, ref.version, record=record, points="\n".join(f"{n}. {p}" for n, p in enumerate(points, 1))
        )
        check = llm.complete_json(role=ROLE, user=prompt, schema=EvidenceCheck, session_id=session_id).value
        by_point = {v.point: v for v in check.verdicts}
        ids: list[str] = []
        held = True
        for n in range(1, len(points) + 1):
            v = by_point.get(n)
            valid = [r for r in (v.record_ids if v else []) if r in known]
            if v is None or v.verdict != "IN_RECORD" or not valid:  # a missing verdict or an invented ID is a no
                held = False
            ids += valid
        out[finding.issue_id] = EvidenceAvailability(in_record=held, record_ids=sorted(set(ids)))
    return out
