"""The evaluation report over evaluated cases (BUILD_PLAN Steps 12, 13, 18; SPEC G1, G2, A4; D-048, D-072).

Three systems, scored on the same cases:
- BENCH: the bench verdict (UNSTABLE counts as no prediction: coverage falls, accuracy is not flattered);
- SINGLE_LLM: one model on the same case file (lexarena/baselines);
- MAJORITY_CLASS: the most common real outcome among the cases *before* this one in the given order (date order in a
  run), so it never sees a label from the future; no earlier label, or a tie, means no prediction.

Verdict level: cases whose real outcome is not MIXED (SPEC I2). Issue level: issues whose court finding is not driven
by EVIDENCE (SPEC A7, F5). For each system: coverage, accuracy with a bootstrap interval, balanced accuracy and
macro-F1 over the predicted rows. BENCH against SINGLE_LLM: the exact McNemar test on the rows both predicted.

Subsets (SPEC G2, A4): HEADLINE (model did not recognise the case, and the case was not decided on evidence), ALL,
MEMORISED, EVIDENCE_DECIDED, and one per split.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from lexarena.evaluator.stats import balanced_accuracy, bootstrap_ci, macro_f1, mcnemar_exact
from lexarena.schemas.base import SIDES, StoredModel
from lexarena.schemas.config import EvaluationConfig
from lexarena.schemas.evaluation import CaseOutcome

System = Literal["BENCH", "SINGLE_LLM", "MAJORITY_CLASS"]
SYSTEMS: tuple[System, ...] = ("BENCH", "SINGLE_LLM", "MAJORITY_CLASS")
VERDICT_LABELS: tuple[str, ...] = SIDES
ISSUE_LABELS: tuple[str, ...] = (*SIDES, "NEITHER")
EXCLUDED_DRIVER = "EVIDENCE"


@dataclass(frozen=True)
class Row:
    """One comparable item: the court's label and each system's prediction (None: no prediction)."""

    truth: str
    predictions: dict[System, str | None]


class SystemScore(StoredModel):
    system: System
    eligible: int
    predicted: int
    coverage: float | None
    accuracy: float | None
    accuracy_ci: tuple[float, float] | None
    balanced_accuracy: float | None
    macro_f1: float | None


class Comparison(StoredModel):
    a: System
    b: System
    pairs: int
    only_a_right: int
    only_b_right: int
    p_value: float


class LevelReport(StoredModel):
    scores: list[SystemScore]
    bench_vs_single_llm: Comparison


class SubsetReport(StoredModel):
    subset: str
    cases: int
    unstable_verdicts: int
    mixed_outcomes: int
    verdict: LevelReport
    issues: LevelReport


class EvaluationReport(StoredModel):
    cases: int
    subsets: list[SubsetReport]
    bootstrap_resamples: int
    confidence_level: float
    seed: int


def _majority(labels: list[str]) -> str | None:
    counts = Counter(labels).most_common()
    if not counts or (len(counts) > 1 and counts[0][1] == counts[1][1]):
        return None
    return counts[0][0]


def _rows(outcomes: Sequence[CaseOutcome]) -> tuple[dict[str, list[Row]], dict[str, list[Row]]]:
    """Per case: verdict rows and issue rows, with the majority-class prediction from earlier cases only."""
    verdicts: dict[str, list[Row]] = {}
    issues: dict[str, list[Row]] = {}
    seen_verdicts: list[str] = []
    seen_issues: list[str] = []
    for o in outcomes:
        single = o.single_llm
        verdict_rows: list[Row] = []
        if o.real_overall != "MIXED":
            verdict_rows.append(
                Row(
                    o.real_overall,
                    {
                        "BENCH": o.bench_winner,
                        "SINGLE_LLM": single.overall if single else None,
                        "MAJORITY_CLASS": _majority(seen_verdicts),
                    },
                )
            )
        issue_majority = _majority(seen_issues)
        issue_rows = [
            Row(
                i.real,
                {
                    "BENCH": i.bench,
                    "SINGLE_LLM": single.issues.get(i.issue_id) if single else None,
                    "MAJORITY_CLASS": issue_majority,
                },
            )
            for i in o.issues
            if i.driver != EXCLUDED_DRIVER
        ]
        verdicts[o.session_id] = verdict_rows
        issues[o.session_id] = issue_rows
        # Learned only after this case is scored: the next case may use it.
        seen_verdicts += [r.truth for r in verdict_rows]
        seen_issues += [r.truth for r in issue_rows]
    return verdicts, issues


def _accuracy(pairs: Sequence[tuple[str, str]]) -> float | None:
    return sum(t == p for t, p in pairs) / len(pairs) if pairs else None


def _score(system: System, rows: list[Row], labels: Sequence[str], cfg: EvaluationConfig, seed: int) -> SystemScore:
    pairs = [(r.truth, p) for r in rows if (p := r.predictions[system]) is not None]
    truth, pred = [t for t, _ in pairs], [p for _, p in pairs]
    return SystemScore(
        system=system,
        eligible=len(rows),
        predicted=len(pairs),
        coverage=len(pairs) / len(rows) if rows else None,
        accuracy=_accuracy(pairs),
        accuracy_ci=bootstrap_ci(
            pairs, _accuracy, resamples=cfg.bootstrap_resamples, level=cfg.confidence_level, seed=seed
        ),
        balanced_accuracy=balanced_accuracy(truth, pred),
        macro_f1=macro_f1(truth, pred, labels),
    )


def _compare(rows: list[Row], a: System, b: System) -> Comparison:
    both = [
        (r.truth, pa, pb) for r in rows if (pa := r.predictions[a]) is not None and (pb := r.predictions[b]) is not None
    ]
    only_a = sum(pa == t and pb != t for t, pa, pb in both)
    only_b = sum(pb == t and pa != t for t, pa, pb in both)
    return Comparison(
        a=a, b=b, pairs=len(both), only_a_right=only_a, only_b_right=only_b, p_value=mcnemar_exact(only_a, only_b)
    )


def _level(rows: list[Row], labels: Sequence[str], cfg: EvaluationConfig, seed: int) -> LevelReport:
    return LevelReport(
        scores=[_score(s, rows, labels, cfg, seed) for s in SYSTEMS],
        bench_vs_single_llm=_compare(rows, "BENCH", "SINGLE_LLM"),
    )


def _subsets(outcomes: Sequence[CaseOutcome]) -> list[tuple[str, Callable[[CaseOutcome], bool]]]:
    subsets: list[tuple[str, Callable[[CaseOutcome], bool]]] = [
        (
            "HEADLINE",
            lambda o: o.memorization_probe == "NOT_IDENTIFIED" and o.evidence_dependency != "EVIDENCE_DECIDED",
        ),
        ("ALL", lambda o: True),
        ("MEMORISED", lambda o: o.memorization_probe == "IDENTIFIED"),
        ("EVIDENCE_DECIDED", lambda o: o.evidence_dependency == "EVIDENCE_DECIDED"),
    ]
    for split in sorted({o.split for o in outcomes}):
        subsets.append((f"SPLIT_{split}", lambda o, s=split: o.split == s))  # type: ignore[misc]
    return subsets


def evaluation_report(outcomes: Sequence[CaseOutcome], cfg: EvaluationConfig, seed: int) -> EvaluationReport:
    """`outcomes` in the order the cases ran (date order in a run); the majority-class baseline depends on it."""
    verdict_rows, issue_rows = _rows(outcomes)
    subsets: list[SubsetReport] = []
    for name, keep in _subsets(outcomes):
        chosen = [o for o in outcomes if keep(o)]
        subsets.append(
            SubsetReport(
                subset=name,
                cases=len(chosen),
                unstable_verdicts=sum(o.bench_status == "UNSTABLE" for o in chosen),
                mixed_outcomes=sum(o.real_overall == "MIXED" for o in chosen),
                verdict=_level([r for o in chosen for r in verdict_rows[o.session_id]], VERDICT_LABELS, cfg, seed),
                issues=_level([r for o in chosen for r in issue_rows[o.session_id]], ISSUE_LABELS, cfg, seed),
            )
        )
    return EvaluationReport(
        cases=len(outcomes),
        subsets=subsets,
        bootstrap_resamples=cfg.bootstrap_resamples,
        confidence_level=cfg.confidence_level,
        seed=seed,
    )
