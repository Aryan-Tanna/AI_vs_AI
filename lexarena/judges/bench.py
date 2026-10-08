"""From opinions to a verdict (D-048, D-051; SPEC E1): pure functions, no I/O, every rule from config.

A persona (`fold_judge`):
- with an INVALID opinion abstains on everything (INVALID_OPINION);
- decides the case only if both presentation orders reached the same overall result, else abstains
  (ORDER_SWAP_DISAGREEMENT, `judging.abstain_on_order_swap_disagreement`);
- decides an issue only if both orders upheld the same side on it.

The bench (`decide_bench`):
- fewer deciding personas than `judging.min_deciding_judges`: UNSTABLE (TOO_FEW_DECIDING_JUDGES). The advocacy score
  is never asked, so it cannot quietly become the verdict (D-051);
- otherwise the majority of deciding personas, with dissent recorded;
- an even split goes to the advocacy score (`judging.tie_break`): the side ahead by at least `judging.tie_margin`
  wins; within the margin the accuracy component decides by the same margin (SPEC E1); within that too, UNSTABLE
  (UNBROKEN_TIE). Never a guess.
- each issue: a strict majority of the personas deciding it, with at least `min_deciding_judges` deciding; otherwise
  UNSTABLE. Issues have no tie-break: the advocacy score ranks argument, not the law of an issue.

The advocacy score per side is the mean, over issues and presentation orders, of the config-weighted dimensions.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from statistics import fmean

from lexarena.schemas.base import SIDES, Side
from lexarena.schemas.bench import (
    BenchIssueFinding,
    BenchVerdict,
    DimensionScores,
    InvalidOpinion,
    JudgeDecision,
    JudgeIssueResult,
    JudgeOpinion,
    Persona,
    PresentationOrder,
    Upholds,
)
from lexarena.schemas.config import JudgingConfig, JudgingWeights

UPHOLDS: tuple[Upholds, ...] = ("PETITIONER", "RESPONDENT", "NEITHER")


class UnsupportedJudgingRuleError(ValueError):
    """A config combination with no defined rule; refused rather than resolved silently."""


def require_supported(cfg: JudgingConfig) -> None:
    if not cfg.abstain_on_order_swap_disagreement:
        raise UnsupportedJudgingRuleError(
            "judging.abstain_on_order_swap_disagreement is false, but no other rule for a persona whose two "
            "presentation orders disagree is defined (D-051); set it true or define the rule first"
        )


def weighted(scores: DimensionScores, w: JudgingWeights) -> float:
    return (
        w.accuracy * scores.accuracy
        + w.consistency * scores.consistency
        + w.rebuttal * scores.rebuttal
        + w.grounding * scores.grounding
    )


def _side_scores(opinions: Iterable[JudgeOpinion], side: Side) -> list[DimensionScores]:
    return [getattr(a, side) for o in opinions for a in o.advocacy]


def advocacy_of(opinions: list[JudgeOpinion], w: JudgingWeights) -> dict[Side, float] | None:
    if not opinions:
        return None
    return {side: fmean(weighted(s, w) for s in _side_scores(opinions, side)) for side in SIDES}


def accuracy_of(opinions: list[JudgeOpinion]) -> dict[Side, float] | None:
    if not opinions:
        return None
    return {side: fmean(s.accuracy for s in _side_scores(opinions, side)) for side in SIDES}


def order_swap_gap(first: JudgeOpinion, second: JudgeOpinion, w: JudgingWeights) -> float:
    """Largest difference in one issue's weighted score for one side between the two orders (SPEC E1)."""
    a = {x.issue_id: x for x in first.advocacy}
    b = {x.issue_id: x for x in second.advocacy}
    gaps = [
        abs(weighted(getattr(a[i], side), w) - weighted(getattr(b[i], side), w))
        for i in sorted(set(a) & set(b))
        for side in SIDES
    ]
    return max(gaps, default=0.0)


def fold_judge(
    persona: Persona,
    opinions: dict[PresentationOrder, JudgeOpinion | InvalidOpinion],
    issue_ids: list[str],
    cfg: JudgingConfig,
    *,
    persona_prompt: str,
    persona_sha256: str,
    persona_approved: bool,
) -> JudgeDecision:
    require_supported(cfg)
    pair = list(opinions.values())
    valid = [o for o in pair if isinstance(o, JudgeOpinion)]
    issue_results: list[JudgeIssueResult] = []
    result: Side | None = None
    reason = None
    if len(valid) < len(pair):
        reason = "INVALID_OPINION"
        issue_results = [JudgeIssueResult(issue_id=i, status="ABSTAINED", upholds=None) for i in issue_ids]
    else:
        first, second = valid
        if first.overall_result == second.overall_result:
            result = first.overall_result
        else:
            reason = "ORDER_SWAP_DISAGREEMENT"
        held = [{d.issue_id: d.upholds for d in o.issue_decisions} for o in valid]
        for i in issue_ids:
            a, b = held[0].get(i), held[1].get(i)
            agreed = a is not None and a == b
            issue_results.append(
                JudgeIssueResult(issue_id=i, status="DECIDED" if agreed else "ABSTAINED", upholds=a if agreed else None)
            )
    both_valid = len(valid) == len(pair)
    return JudgeDecision(
        judge=persona,
        persona_prompt=persona_prompt,
        persona_sha256=persona_sha256,
        persona_approved=persona_approved,
        opinions=pair,
        status="DECIDED" if result is not None else "ABSTAINED",
        result=result,
        abstain_reason=reason,
        issue_results=issue_results,
        order_swap_gap=order_swap_gap(valid[0], valid[1], cfg.weights) if both_valid else None,
        advocacy=advocacy_of(valid, cfg.weights),
    )


def _issue_finding(issue_id: str, decisions: list[JudgeDecision], cfg: JudgingConfig) -> BenchIssueFinding:
    votes: dict[Persona, Upholds] = {}
    for d in decisions:
        for r in d.issue_results:
            if r.issue_id == issue_id and r.upholds is not None:
                votes[d.judge] = r.upholds
    counts = Counter(votes.values())
    tally: dict[Upholds, int] = {u: counts.get(u, 0) for u in UPHOLDS}
    deciding = list(votes)
    top, top_count = max(tally.items(), key=lambda kv: kv[1])
    strict_majority = top_count > len(deciding) - top_count
    if len(deciding) >= cfg.min_deciding_judges and strict_majority:
        return BenchIssueFinding(
            issue_id=issue_id,
            status="DECIDED",
            upholds=top,
            votes=tally,
            deciding_judges=deciding,
            dissenting_judges=[p for p, u in votes.items() if u != top],
        )
    return BenchIssueFinding(
        issue_id=issue_id, status="UNSTABLE", upholds=None, votes=tally, deciding_judges=deciding, dissenting_judges=[]
    )


def _bench_scores(
    decisions: list[JudgeDecision], cfg: JudgingConfig
) -> tuple[dict[Side, float] | None, dict[Side, float] | None]:
    valid = [o for d in decisions for o in d.opinions if isinstance(o, JudgeOpinion)]
    return advocacy_of(valid, cfg.weights), accuracy_of(valid)


def _ahead(scores: dict[Side, float] | None, margin: float) -> Side | None:
    if scores is None:
        return None
    p, r = scores["PETITIONER"], scores["RESPONDENT"]
    if abs(p - r) < margin:
        return None
    return "PETITIONER" if p > r else "RESPONDENT"


def decide_bench(decisions: list[JudgeDecision], issue_ids: list[str], cfg: JudgingConfig) -> BenchVerdict:
    require_supported(cfg)
    deciding = [d for d in decisions if d.result is not None]
    votes: dict[Side, int] = {side: sum(d.result == side for d in deciding) for side in SIDES}
    advocacy, accuracy = _bench_scores(decisions, cfg)
    common = {
        "votes": votes,
        "deciding_judges": [d.judge for d in deciding],
        "abstaining_judges": [d.judge for d in decisions if d.result is None],
        "issue_findings": [_issue_finding(i, decisions, cfg) for i in issue_ids],
        "advocacy": advocacy,
    }

    def unstable(reason: str) -> BenchVerdict:
        return BenchVerdict.model_validate(
            {**common, "status": "UNSTABLE", "winner": None, "decided_by": None, "unstable_reason": reason}
            | {"dissenting_judges": []}
        )

    if len(deciding) < cfg.min_deciding_judges:
        return unstable("TOO_FEW_DECIDING_JUDGES")
    if votes["PETITIONER"] != votes["RESPONDENT"]:
        winner: Side = "PETITIONER" if votes["PETITIONER"] > votes["RESPONDENT"] else "RESPONDENT"
        decided_by = "MAJORITY"
    else:
        tie_winner = _ahead(advocacy, cfg.tie_margin) or _ahead(accuracy, cfg.tie_margin)
        if tie_winner is None:
            return unstable("UNBROKEN_TIE")
        winner, decided_by = tie_winner, "TIE_BREAK"
    return BenchVerdict.model_validate(
        {
            **common,
            "status": "DECIDED",
            "winner": winner,
            "decided_by": decided_by,
            "unstable_reason": None,
            "dissenting_judges": [d.judge for d in deciding if d.result != winner],
        }
    )
