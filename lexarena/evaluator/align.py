"""Bench against the real judgment, after the verdict (BUILD_PLAN Step 12; ARCHITECTURE §6; SPEC G2, I2; D-072).

Pure comparison, no model calls:
- per issue: what the bench held (None when UNSTABLE) against what the court held, with the court's `driver`;
- `issue_alignment`: the share of compared issues the bench decided as the court did. Compared means the bench
  decided the issue and the court's finding was not driven by EVIDENCE: on evidence-driven issues the agents never had
  what decided them (SPEC A7, F5), so a mismatch there measures the record, not the bench; D-151: unless the check
  after the verdict found that evidence in their record. Every issue is still stored,
  so a report can recompute any other subset;
- `winner_matches_real`: only when the court's overall outcome is not MIXED (SPEC I2) and the bench verdict is DECIDED
  (an UNSTABLE verdict is reported apart, never counted as right or wrong; D-051).
"""

from __future__ import annotations

from collections.abc import Mapping

from lexarena.evaluator.evidence import EvidenceAvailability
from lexarena.schemas.bench import BenchVerdict
from lexarena.schemas.ground_truth import CaseGroundTruth
from lexarena.schemas.session import Evaluation, IssueAlignment

EXCLUDED_DRIVER = "EVIDENCE"


def issue_alignments(
    bench: BenchVerdict,
    truth: CaseGroundTruth,
    framed_issue_ids: list[str],
    evidence: Mapping[str, EvidenceAvailability] | None = None,
) -> list[IssueAlignment]:
    held = {f.issue_id: f.upholds for f in bench.issue_findings}
    real = {f.issue_id: f for f in truth.issue_findings}
    out: list[IssueAlignment] = []
    for issue_id in framed_issue_ids:
        finding = real.get(issue_id)
        if finding is None:  # the court made no finding on a framed issue: nothing to compare
            continue
        bench_upholds = held.get(issue_id)
        seen = (evidence or {}).get(issue_id)
        out.append(
            IssueAlignment(
                issue_id=issue_id,
                bench=bench_upholds,
                real=finding.favours,
                driver=finding.driver,
                aligned=None if bench_upholds is None else bench_upholds == finding.favours,
                evidence_in_record=None if seen is None else seen.in_record,
                evidence_record_ids=[] if seen is None else seen.record_ids,
            )
        )
    return out


def evaluate(
    bench: BenchVerdict,
    truth: CaseGroundTruth,
    framed_issue_ids: list[str],
    evidence: Mapping[str, EvidenceAvailability] | None = None,
) -> Evaluation:
    """`evidence` (D-151): an EVIDENCE issue whose evidence was in the advocates' record is compared like the rest."""
    issues = issue_alignments(bench, truth, framed_issue_ids, evidence)
    compared = [
        i.aligned
        for i in issues
        if i.aligned is not None and (i.driver != EXCLUDED_DRIVER or i.evidence_in_record is True)
    ]
    real_overall = truth.conclusion.overall_favours
    winner_matches = None if real_overall == "MIXED" or bench.winner is None else bench.winner == real_overall
    return Evaluation(
        winner_matches_real=winner_matches,
        issue_alignment=sum(compared) / len(compared) if compared else None,
        real_overall=real_overall,
        issues=issues,
    )
