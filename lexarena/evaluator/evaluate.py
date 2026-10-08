"""The evaluator's job for one session (BUILD_PLAN Step 12; ARCHITECTURE §6; non-negotiable 6; D-072).

Runs only in the sealed process, as the EVALUATOR role. Ground truth is read through `GroundTruthRepository.get`, which
refuses unless the session is about this case and its verdict is recorded; the repository checks that from the stored
session state, so nothing here can open the seal early. The evaluation is written by the VERDICT_RECORDED -> EVALUATED
transition, which only the evaluator may make.
"""

from __future__ import annotations

from dataclasses import dataclass

from lexarena.evaluator.align import evaluate
from lexarena.schemas.evaluation import BaselinePrediction, CaseOutcome
from lexarena.schemas.session import Session
from lexarena.storage.factory import EvaluatorStores


class NotEvaluableError(RuntimeError):
    """A session the evaluator cannot compare: no bench verdict (pre-D-048), or not yet at VERDICT_RECORDED."""


@dataclass(frozen=True)
class EvaluationResult:
    session: Session
    outcome: CaseOutcome


def evaluate_session(
    stores: EvaluatorStores, session_id: str, single_llm: BaselinePrediction | None = None
) -> EvaluationResult:
    session = stores.sessions.get(session_id)
    if session.bench is None:
        raise NotEvaluableError(f"session {session_id} has no bench verdict (state {session.state})")
    case = stores.cases.get(session.case_id)
    truth = stores.ground_truth.get(session.case_id, session_id=session_id)  # refuses before the verdict
    framed = [i.issue_id for i in case.agent_view.framed_issues]
    evaluation = evaluate(session.bench, truth, framed)
    stored = stores.sessions.record_evaluation(session_id, evaluation)
    outcome = CaseOutcome(
        case_id=case.id,
        session_id=session_id,
        split=session.split,
        evidence_dependency=case.build.evidence_dependency,
        memorization_probe=case.build.memorization_probe,
        bench_status=session.bench.status,
        bench_winner=session.bench.winner,
        real_overall=truth.conclusion.overall_favours,
        issues=evaluation.issues,
        single_llm=single_llm if single_llm is not None and single_llm.case_id == case.id else None,
    )
    return EvaluationResult(session=stored, outcome=outcome)
