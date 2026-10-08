"""Bench diagnostics over many sessions (BUILD_PLAN Step 11 "done when"; SPEC E1; D-024, D-071).

Per persona: how often its two presentation orders disagreed on the result (against
`judging.max_order_swap_disagreement_rate`), the distribution of its order-swap score gap (against
`judging.order_swap_max_gap`), how often it abstained and why, how often it needed its revision or stayed invalid,
and its win rate by side (flagged above `judging.persona_role_max_win_rate` once it has decided at least
`judging.persona_role_min_cases` cases). The limits are read from config, fixed before measuring; this module only
reports against them.
"""

from __future__ import annotations

from collections import Counter
from statistics import median

from lexarena.schemas.base import SIDES, Side, StoredModel
from lexarena.schemas.bench import PERSONAS, BenchVerdict, InvalidOpinion, JudgeDecision, JudgeOpinion, Persona
from lexarena.schemas.config import JudgingConfig


class GapStats(StoredModel):
    count: int
    minimum: float | None
    median: float | None
    maximum: float | None
    over_limit: int


class PersonaReport(StoredModel):
    persona: Persona
    cases: int
    decided: int
    abstained: dict[str, int]
    order_swap_disagreement_rate: float | None
    disagreement_over_limit: bool
    issue_disagreement_rate: float | None
    gap: GapStats
    revised_opinions: int
    invalid_opinions: int
    unapproved_runs: int
    wins: dict[Side, int]
    role_bias_flag: Side | None


class BenchReport(StoredModel):
    sessions: int
    verdicts: dict[str, int]
    personas: list[PersonaReport]
    limits: dict[str, float]


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def persona_report(persona: Persona, decisions: list[JudgeDecision], cfg: JudgingConfig) -> PersonaReport:
    mine = [d for d in decisions if d.judge == persona]
    both_valid = [d for d in mine if all(isinstance(o, JudgeOpinion) for o in d.opinions)]
    disagreed = sum(d.abstain_reason == "ORDER_SWAP_DISAGREEMENT" for d in mine)
    issues = [r for d in both_valid for r in d.issue_results]
    gaps = sorted(d.order_swap_gap for d in mine if d.order_swap_gap is not None)
    opinions = [o for d in mine for o in d.opinions]
    wins: dict[Side, int] = {side: sum(d.result == side for d in mine) for side in SIDES}
    decided = sum(wins.values())
    bias: Side | None = None
    if decided >= cfg.persona_role_min_cases:
        top = max(SIDES, key=lambda s: wins[s])
        if wins[top] / decided > cfg.persona_role_max_win_rate:
            bias = top
    rate = _rate(disagreed, len(both_valid))
    return PersonaReport(
        persona=persona,
        cases=len(mine),
        decided=decided,
        abstained=dict(Counter(d.abstain_reason for d in mine if d.abstain_reason is not None)),
        order_swap_disagreement_rate=rate,
        disagreement_over_limit=rate is not None and rate > cfg.max_order_swap_disagreement_rate,
        issue_disagreement_rate=_rate(sum(r.status == "ABSTAINED" for r in issues), len(issues)),
        gap=GapStats(
            count=len(gaps),
            minimum=gaps[0] if gaps else None,
            median=median(gaps) if gaps else None,
            maximum=gaps[-1] if gaps else None,
            over_limit=sum(g > cfg.order_swap_max_gap for g in gaps),
        ),
        revised_opinions=sum(o.revised for o in opinions),
        invalid_opinions=sum(isinstance(o, InvalidOpinion) for o in opinions),
        unapproved_runs=sum(not d.persona_approved for d in mine),
        wins=wins,
        role_bias_flag=bias,
    )


def bench_report(sessions: list[tuple[list[JudgeDecision], BenchVerdict]], cfg: JudgingConfig) -> BenchReport:
    decisions = [d for ds, _ in sessions for d in ds]
    verdicts = Counter(v.winner or f"UNSTABLE_{v.unstable_reason}" for _, v in sessions)
    return BenchReport(
        sessions=len(sessions),
        verdicts=dict(verdicts),
        personas=[persona_report(p, decisions, cfg) for p in PERSONAS],
        limits={
            "order_swap_max_gap": cfg.order_swap_max_gap,
            "max_order_swap_disagreement_rate": cfg.max_order_swap_disagreement_rate,
            "persona_role_max_win_rate": cfg.persona_role_max_win_rate,
            "persona_role_min_cases": cfg.persona_role_min_cases,
        },
    )
