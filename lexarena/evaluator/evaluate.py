"""The evaluator's job for one session (BUILD_PLAN Step 12; ARCHITECTURE §6; non-negotiable 6; D-072).

Runs only in the sealed process, as the EVALUATOR role. Ground truth is read through `GroundTruthRepository.get`, which
refuses unless the session is about this case and its verdict is recorded; the repository checks that from the stored
session state, so nothing here can open the seal early. The evaluation is written by the VERDICT_RECORDED -> EVALUATED
transition, which only the evaluator may make.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from lexarena.evaluator.align import evaluate
from lexarena.evaluator.evidence import EvidenceAvailability
from lexarena.schemas.case import AgentCaseView
from lexarena.schemas.evaluation import BaselinePrediction, CaseOutcome
from lexarena.schemas.ground_truth import CaseGroundTruth
from lexarena.schemas.session import Session
from lexarena.storage.factory import EvaluatorStores

MIN_NAME_WORD = 4  # literal-ok: shorter fragments ("Ltd", "Co") are too common to mark a name
NAME_WORDS_FOR_RECALL = 2  # literal-ok: two distinct words of one real name = the model named that party


def recalled_names(
    texts: Iterable[str],
    real_names: Iterable[str],
    generic_words: Iterable[str],
    shown_texts: Iterable[str] = (),
) -> list[str]:
    """D-145 (D-143 made automatic): real party names a model wrote in this session's reasoning or outputs. A name
    counts when written in full, or when two distinct distinctive words of it appear as written in the name (same
    capitalisation), so ordinary words that happen to be in a name ("Capital") do not count on their own. A name that
    appears in what the session showed the models (`shown_texts`: precedent titles and lookup answers) is not memory
    (D-147: in DEV_0013 a bank party's name came from precedent titles the lawyers were served)."""
    shown = "\n".join(shown_texts).lower()
    generic = {w.lower() for w in generic_words}
    text = "\n".join(texts)
    low = text.lower()
    hits: list[str] = []
    for name in real_names:
        full = " ".join(name.split())
        if full.lower() in shown:
            continue
        words = [
            w for w in re.findall(r"[A-Za-z][A-Za-z'.-]+", name) if len(w) >= MIN_NAME_WORD and w.lower() not in generic
        ]
        if len(full) >= MIN_NAME_WORD and len(full.split()) > 1 and full.lower() in low:
            hits.append(name)
            continue
        found = {w for w in words if re.search(rf"\b{re.escape(w)}\b", text)}
        if len(found) >= NAME_WORDS_FOR_RECALL:
            hits.append(name)
    return hits


def scanned_names(anonymization_map: dict[str, str], skip_kinds: Iterable[str]) -> list[str]:
    """D-148: the real names the scan looks for, leaving out parties whose pseudonym kind (the word before the hyphen,
    e.g. "Bank-A") is in `clerk.recall_scan_skips_kinds`. Banks and authorities appear in many unrelated judgments a
    model may name from general memory (DEV_0014), so naming one alone is not recall of this case."""
    skip = set(skip_kinds)
    return [name for pseudonym, name in anonymization_map.items() if pseudonym.split("-")[0] not in skip]


class NotEvaluableError(RuntimeError):
    """A session the evaluator cannot compare: no bench verdict (pre-D-048), or not yet at VERDICT_RECORDED."""


@dataclass(frozen=True)
class EvaluationResult:
    session: Session
    outcome: CaseOutcome


def evaluate_session(
    stores: EvaluatorStores,
    session_id: str,
    single_llm: BaselinePrediction | None = None,
    model_texts: list[str] | None = None,
    generic_words: Iterable[str] = (),
    shown_texts: list[str] | None = None,
    skip_kinds: Iterable[str] = (),
    evidence_check: Callable[[AgentCaseView, CaseGroundTruth], Mapping[str, EvidenceAvailability]] | None = None,
) -> EvaluationResult:
    """`model_texts`: every model's reasoning and output in this session (its trace), scanned for the real names
    after the verdict (D-145); a case a model named is reported with the memorised cases."""
    session = stores.sessions.get(session_id)
    if session.bench is None:
        raise NotEvaluableError(f"session {session_id} has no bench verdict (state {session.state})")
    case = stores.cases.get(session.case_id)
    truth = stores.ground_truth.get(session.case_id, session_id=session_id)  # refuses before the verdict
    framed = [i.issue_id for i in case.agent_view.framed_issues]
    names = scanned_names(truth.anonymization_map, skip_kinds)
    recalled = recalled_names(model_texts or [], names, generic_words, shown_texts or [])
    # D-151: after the verdict, with the unsealed truth; only yes/no and record IDs reach the stored evaluation.
    evidence = evidence_check(stores.cases.agent_view(case.id), truth) if evidence_check is not None else None
    evaluation = evaluate(session.bench, truth, framed, evidence)
    stored = stores.sessions.record_evaluation(session_id, evaluation)
    outcome = CaseOutcome(
        case_id=case.id,
        session_id=session_id,
        split=session.split,
        evidence_dependency=case.build.evidence_dependency,
        memorization_probe="IDENTIFIED" if recalled else case.build.memorization_probe,
        recalled_names=recalled,
        bench_status=session.bench.status,
        bench_winner=session.bench.winner,
        real_overall=truth.conclusion.overall_favours,
        issues=evaluation.issues,
        single_llm=single_llm if single_llm is not None and single_llm.case_id == case.id else None,
    )
    return EvaluationResult(session=stored, outcome=outcome)
