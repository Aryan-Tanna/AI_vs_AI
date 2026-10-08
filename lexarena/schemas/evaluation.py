"""Baselines and per-case outcomes for the evaluation report (BUILD_PLAN Steps 12, 13, 18; SPEC G1, G2; D-072).

`SingleLLMDraft` is what the single-LLM baseline model returns; `BaselinePrediction` is what is kept of it. A
`CaseOutcome` is one evaluated case as the report sees it: the bench's result, the court's, the case's build labels
that decide which subset it is reported in, and the baselines' predictions. Real outcomes appear here only after the
case's verdict was recorded and evaluated.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from lexarena.schemas.base import NonEmptyStr, Side, StoredModel
from lexarena.schemas.bench import Upholds
from lexarena.schemas.case import CaseId, IssueId, Split
from lexarena.schemas.session import IssueAlignment


class BaselineIssueDraft(StoredModel):
    issue_id: str
    upholds: Upholds


class SingleLLMDraft(StoredModel):
    issue_decisions: list[BaselineIssueDraft]
    overall_result: Side
    reasons: str


class BaselinePrediction(StoredModel):
    case_id: CaseId
    kind: Literal["SINGLE_LLM"]
    model: NonEmptyStr
    prompt_id: NonEmptyStr
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    overall: Side
    issues: dict[IssueId, Upholds]  # framed issues it decided; a missing or unknown issue is not a prediction
    problems: list[NonEmptyStr]


class CaseOutcome(StoredModel):
    case_id: CaseId
    session_id: NonEmptyStr
    split: Split
    evidence_dependency: Literal["LAW_ONLY", "MIXED", "EVIDENCE_DECIDED"]
    memorization_probe: Literal["NOT_IDENTIFIED", "IDENTIFIED"]
    bench_status: Literal["DECIDED", "UNSTABLE"]
    bench_winner: Side | None
    real_overall: Literal["PETITIONER", "RESPONDENT", "MIXED"]
    issues: list[IssueAlignment]
    single_llm: BaselinePrediction | None
