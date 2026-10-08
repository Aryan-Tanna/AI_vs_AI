"""Builders for bench objects (schemas/bench.py) used in tests. Placeholder text only (non-negotiable 1)."""

from __future__ import annotations

from typing import Any

from lexarena.schemas.base import Side
from lexarena.schemas.bench import (
    DimensionScores,
    IssueAdvocacyDraft,
    IssueDecisionDraft,
    JudgeOpinion,
    OpinionDraft,
    Persona,
    PresentationOrder,
    Upholds,
)

SHA = "0" * 64


def scores(value: float) -> DimensionScores:
    return DimensionScores(accuracy=value, consistency=value, rebuttal=value, grounding=value)


def opinion(
    order: PresentationOrder,
    result: Side,
    upholds: dict[str, Upholds],
    *,
    p_score: float = 0.5,
    r_score: float = 0.5,
    p_dims: DimensionScores | None = None,
    r_dims: DimensionScores | None = None,
) -> JudgeOpinion:
    p, r = p_dims or scores(p_score), r_dims or scores(r_score)
    return JudgeOpinion.model_validate(
        {
            "order": order,
            "issue_decisions": [
                {
                    "issue_id": issue,
                    "finding": "<finding>",
                    "governing_rule_ids": ["<statute>"],
                    "record_ids": ["F1"],
                    "application": "<application>",
                    "conclusion": "<conclusion>",
                    "upholds": side,
                }
                for issue, side in upholds.items()
            ],
            "overall_result": result,
            "overall_reasons": "<reasons>",
            "advocacy": [{"issue_id": issue, "PETITIONER": p, "RESPONDENT": r} for issue in upholds],
            "revised": False,
        }
    )


def opinion_pair(
    result: Side | tuple[Side, Side],
    upholds: dict[str, Upholds] | tuple[dict[str, Upholds], dict[str, Upholds]],
    **kwargs: Any,
) -> dict[PresentationOrder, JudgeOpinion]:
    first, second = result if isinstance(result, tuple) else (result, result)
    up1, up2 = upholds if isinstance(upholds, tuple) else (upholds, upholds)
    return {
        "PETITIONER_FIRST": opinion("PETITIONER_FIRST", first, up1, **kwargs),
        "RESPONDENT_FIRST": opinion("RESPONDENT_FIRST", second, up2, **kwargs),
    }


def draft(
    result: Side,
    decisions: list[dict[str, Any]],
    *,
    advocacy_issues: list[str] | None = None,
) -> OpinionDraft:
    issues = advocacy_issues if advocacy_issues is not None else [d["issue_id"] for d in decisions]
    return OpinionDraft(
        issue_decisions=[
            IssueDecisionDraft.model_validate(
                {
                    "finding": "<finding>",
                    "application": "<application>",
                    "conclusion": "<conclusion>",
                    "record_ids": [],
                    **d,
                }
            )
            for d in decisions
        ],
        overall_result=result,
        overall_reasons="<reasons>",
        advocacy=[IssueAdvocacyDraft(issue_id=i, petitioner=scores(0.5), respondent=scores(0.5)) for i in issues],
    )


PERSONA: Persona = "TEXTUALIST"
