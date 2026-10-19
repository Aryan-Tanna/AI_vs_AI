"""Hearing metrics in code, after the verdict (D-137). No model calls except the local embedder for novelty.

Per side: issue coverage, rebuttal depth and consistency (THEMIS-GLOBAL), verification health (hard errors, retries,
first-try rate, FLAGGED turns, citation tiers), repetition (share of each turn's sentences copied from the side's own
earlier turns, the THEMIS measure, D-154), and prerequisite warnings. Bench: abstentions, judges whose two presentation
orders disagree, and how often the side presented first wins. Reasoning alignment: the statutes and precedents the deciding
judges rested on against those the real court analysed and followed (precision and recall).

Report-only: never shown to agents or judges, never a gate, nothing is tuned on test-set values (non-negotiable 9).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Sequence
from statistics import fmean

from lexarena.embedding import Embedder
from lexarena.schemas.base import SIDES, Side
from lexarena.schemas.bench import JudgeDecision, JudgeOpinion
from lexarena.schemas.ground_truth import CaseGroundTruth
from lexarena.schemas.metrics import BenchMetrics, HearingMetrics, ReasoningAlignment, SideMetrics
from lexarena.schemas.session import Session
from lexarena.schemas.transcript import PrivateTurnData, PublishedTurn
from lexarena.themis_local.audit import PREREQUISITE_UNADDRESSED
from lexarena.themis_local.layer2 import sentences

RELIED_ON = ("FOLLOWED", "APPLIED")  # precedent treatments that make a precedent part of the court's governing law
UID_SEPARATOR = "#"  # a precedent UID is "<precedent_id>#<hash>"
YEAR_DIGITS = 4  # literal-ok: a precedent ID opens with its four-digit year (DATA_FORMATS)
FIRST = {"PETITIONER_FIRST": "PETITIONER", "RESPONDENT_FIRST": "RESPONDENT"}


def _cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else 0.0


def repetition_series(texts: list[str], embedder: Embedder, sentence_similarity: float) -> list[float]:
    """For each turn after the first, the share of its sentences that nearly copy a sentence of the same side's earlier
    turns (D-154, the THEMIS measure; whole-turn similarity read 0.91-0.96 between honest turns)."""
    split = [sentences(t) for t in texts]
    flat = [s for ss in split for s in ss]
    vectors = iter(embedder.embed(flat) if flat else [])
    per_turn = [[next(vectors) for _ in ss] for ss in split]
    out: list[float] = []
    for i in range(1, len(texts)):
        said = [v for vs in per_turn[:i] for v in vs]
        mine = per_turn[i]
        if not mine or not said:
            out.append(0.0)
            continue
        copied = sum(1 for v in mine if max(_cosine(v, w) for w in said) >= sentence_similarity)
        out.append(copied / len(mine))
    return out


def _share(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def _global(session: Session, block: str, side: Side, key: str) -> float | None:
    if session.themis_global is None:
        return None
    value = getattr(session.themis_global, block).get(side, {}).get(key)
    return float(value) if isinstance(value, int | float) else None


def side_metrics(
    side: Side,
    session: Session,
    turns: list[PublishedTurn],
    private: list[PrivateTurnData],
    framed: list[str],
    embedder: Embedder,
    sentence_similarity: float,
) -> SideMetrics:
    own = [t for t in turns if t.speaker == side]
    addressed = {i for t in own for i in t.issues_addressed}
    reps = repetition_series([t.published_text for t in own], embedder, sentence_similarity)
    results = [p.themis_local for p in private]
    tiers = Counter(a.citation_tier for p in private for a in p.claim_assessments if a.citation_tier is not None)
    return SideMetrics(
        turns=len(own),
        issue_coverage=_share(len(addressed & set(framed)), len(framed)),
        rebuttal_depth=_global(session, "rebuttal_depth", side, "depth"),
        consistency=_global(session, "consistency", side, "score"),
        hard_errors=sum(len(attempt) for r in results for attempt in r.hard_errors_by_attempt),
        retries=sum(r.attempts - 1 for r in results),
        first_try_rate=_share(sum(r.attempts == 1 for r in results), len(results)),
        flagged_turns=sum(r.outcome == "FLAGGED" for r in results),
        citation_tiers=dict(sorted(tiers.items())),
        mean_repetition=fmean(reps) if reps else None,
        max_repetition=max(reps) if reps else None,
        prerequisite_warnings=sum(w.code == PREREQUISITE_UNADDRESSED for r in results for w in r.warnings),
    )


def _valid(decision: JudgeDecision) -> list[JudgeOpinion]:
    return [o for o in decision.opinions if isinstance(o, JudgeOpinion)]


def bench_metrics(decisions: Sequence[JudgeDecision]) -> BenchMetrics:
    order_flips = issue_flips = first_wins = opinions = 0
    for d in decisions:
        valid = _valid(d)
        opinions += len(valid)
        first_wins += sum(o.overall_result == FIRST[o.order] for o in valid)
        if len(valid) == len(FIRST):
            a, b = valid
            order_flips += a.overall_result != b.overall_result
            held = {i.issue_id: i.upholds for i in b.issue_decisions}
            issue_flips += sum(held.get(i.issue_id, i.upholds) != i.upholds for i in a.issue_decisions)
    return BenchMetrics(
        judges=len(decisions),
        abstentions=sum(d.status == "ABSTAINED" for d in decisions),
        opinions=opinions,
        order_flips=order_flips,
        issue_order_flips=issue_flips,
        first_presented_wins=first_wins,
    )


def _same_statute(a: str, b: str) -> bool:
    """A section and its sub-provision match ("<ACT>_SEC_5" and "<ACT>_SEC_5_8")."""
    return a == b or a.startswith(b + "_") or b.startswith(a + "_")


def _exact(a: str, b: str) -> bool:
    return a == b


def _precision_recall(
    bench: set[str], real: set[str], match: Callable[[str, str], bool]
) -> tuple[float | None, float | None]:
    hit_bench = sum(any(match(x, y) for y in real) for x in bench)
    hit_real = sum(any(match(y, x) for x in bench) for y in real)
    return _share(hit_bench, len(bench)), _share(hit_real, len(real))


def is_precedent(rule_id: str) -> bool:
    """Precedent IDs start with their year ("2020_NCLAT_DEL_1", UIDs add "#<hash>"); statute IDs never do."""
    return UID_SEPARATOR in rule_id or rule_id[:YEAR_DIGITS].isdigit()


def reasoning_alignment(decisions: Sequence[JudgeDecision], truth: CaseGroundTruth) -> ReasoningAlignment:
    rules = {
        r
        for d in decisions
        if d.status == "DECIDED"
        for o in _valid(d)
        for i in o.issue_decisions
        for r in i.governing_rule_ids
    }
    bench_statutes = {r for r in rules if not is_precedent(r)}
    bench_precedents = {r.split(UID_SEPARATOR)[0] for r in rules - bench_statutes}
    real_statutes = {s.statute_id for s in truth.statutory_analysis}
    real_precedents = {p.precedent_id for p in truth.precedent_analysis if p.precedent_id and p.treatment in RELIED_ON}
    sp, sr = _precision_recall(bench_statutes, real_statutes, _same_statute)
    pp, pr = _precision_recall(bench_precedents, real_precedents, _exact)
    return ReasoningAlignment(
        real_statutes=sorted(real_statutes),
        bench_statutes=sorted(bench_statutes),
        statute_precision=sp,
        statute_recall=sr,
        real_precedents=sorted(real_precedents),
        bench_precedents=sorted(bench_precedents),
        precedent_precision=pp,
        precedent_recall=pr,
    )


def hearing_metrics(
    session: Session,
    turns: list[PublishedTurn],
    private: dict[Side, list[PrivateTurnData]],
    truth: CaseGroundTruth,
    framed: list[str],
    embedder: Embedder,
    sentence_similarity: float,
) -> HearingMetrics:
    return HearingMetrics(
        session_id=session.id,
        case_id=session.case_id,
        sides={s: side_metrics(s, session, turns, private[s], framed, embedder, sentence_similarity) for s in SIDES},
        bench=bench_metrics(session.judge_decisions),
        reasoning=reasoning_alignment(session.judge_decisions, truth),
    )


def _mean(values: list[float | None]) -> float | None:
    got = [v for v in values if v is not None]
    return fmean(got) if got else None


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def render_markdown(run_id: str, metrics: list[HearingMetrics]) -> str:
    """Per-case rows, then the per-side means across cases (a gap between the sides is a bias signal)."""
    lines = [f"# Hearing metrics: {run_id}", "", f"{len(metrics)} evaluated session(s). Report-only (D-137).", ""]
    lines += [
        "| Case | Side | Issues covered | Rebuttal depth | Consistency | Hard errors | Retries | First try | "
        "Mean repetition | Max repetition | Prereq. warnings |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for m in metrics:
        for side in SIDES:
            s = m.sides[side]
            lines.append(
                f"| {m.case_id} | {side} | {_fmt(s.issue_coverage)} | {_fmt(s.rebuttal_depth)} | {_fmt(s.consistency)}"
                f" | {s.hard_errors} | {s.retries} | {_fmt(s.first_try_rate)} | {_fmt(s.mean_repetition)}"
                f" | {_fmt(s.max_repetition)} | {s.prerequisite_warnings} |"
            )
    lines += ["", "## Per side, mean over cases", "", "| Metric | PETITIONER | RESPONDENT |", "| --- | --- | --- |"]
    for name in ("issue_coverage", "rebuttal_depth", "consistency", "first_try_rate", "mean_repetition"):
        row = [_fmt(_mean([getattr(m.sides[side], name) for m in metrics])) for side in SIDES]
        lines.append(f"| {name} | {row[0]} | {row[1]} |")
    for name in ("hard_errors", "retries", "flagged_turns", "prerequisite_warnings"):
        row = [str(sum(getattr(m.sides[side], name) for m in metrics)) for side in SIDES]
        lines.append(f"| {name} (total) | {row[0]} | {row[1]} |")
    lines += ["", "## Bench and reasoning", "", "| Case | Judges | Abstained | Order flips | Issue flips |"
              " First-presented wins / opinions | Statutes P/R | Precedents P/R |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    for m in metrics:
        b, r = m.bench, m.reasoning
        lines.append(
            f"| {m.case_id} | {b.judges} | {b.abstentions} | {b.order_flips} | {b.issue_order_flips}"
            f" | {b.first_presented_wins} / {b.opinions} | {_fmt(r.statute_precision)} / {_fmt(r.statute_recall)}"
            f" | {_fmt(r.precedent_precision)} / {_fmt(r.precedent_recall)} |"
        )
    wins = sum(m.bench.first_presented_wins for m in metrics)
    total = sum(m.bench.opinions for m in metrics)
    lines += ["", f"Side presented first wins {wins} of {total} valid opinions (about half means no order bias)."]
    return "\n".join(lines) + "\n"
