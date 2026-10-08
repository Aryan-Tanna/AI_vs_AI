"""`sessions` collection (SPEC H4) and the session state machine.

The state is what unseals ground truth: `case_ground_truth` is readable only while the session is in
an `UNSEALED_STATES` state, and only by the evaluator and the reflection engine (CLAUDE.md §10).
States move forward only, along `TRANSITIONS`; nothing returns to a sealed state once unsealed.

The verdict is the bench's reasoned decision (D-048): `bench` and `judge_decisions` (schemas/bench.py). `winner` and
`aggregate` mirror it for readers of the SPEC H4 shape: `winner` is the bench winner, or UNSTABLE, and `aggregate` is
the secondary advocacy score. `judge_scorecards` is the pre-D-048 score-only form, kept so older documents validate.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from lexarena.schemas.base import SIDES, NonEmptyStr, StoredModel, UnitScore
from lexarena.schemas.bench import BenchVerdict, DimensionScores, JudgeDecision, Upholds
from lexarena.schemas.case import CaseId, IssueId, Split


class SessionState(StrEnum):
    CREATED = "CREATED"
    IN_PROGRESS = "IN_PROGRESS"
    VERDICT_RECORDED = "VERDICT_RECORDED"
    EVALUATED = "EVALUATED"
    REFLECTED = "REFLECTED"
    ABORTED = "ABORTED"


TRANSITIONS: dict[SessionState, frozenset[SessionState]] = {
    SessionState.CREATED: frozenset({SessionState.IN_PROGRESS, SessionState.ABORTED}),
    SessionState.IN_PROGRESS: frozenset({SessionState.VERDICT_RECORDED, SessionState.ABORTED}),
    SessionState.VERDICT_RECORDED: frozenset({SessionState.EVALUATED}),
    SessionState.EVALUATED: frozenset({SessionState.REFLECTED}),
    SessionState.REFLECTED: frozenset(),
    SessionState.ABORTED: frozenset(),
}
UNSEALED_STATES = frozenset({SessionState.VERDICT_RECORDED, SessionState.EVALUATED, SessionState.REFLECTED})
EVALUATED_STATES = frozenset({SessionState.EVALUATED, SessionState.REFLECTED})


class VersionStamp(StoredModel):
    """CLAUDE.md §10: every session records what produced it. `memory_snapshot` proves frozen test memory."""

    git_sha: NonEmptyStr
    config_version: NonEmptyStr
    config_sha256: NonEmptyStr
    law_db_snapshot: NonEmptyStr
    precedent_db_snapshot: NonEmptyStr
    memory_snapshot: NonEmptyStr


class SessionConfig(StoredModel):
    lawyer_model: NonEmptyStr
    judge_model: NonEmptyStr
    seed: int


class IssueScore(StoredModel):
    issue_id: IssueId
    order: Literal["PETITIONER_FIRST", "RESPONDENT_FIRST"]
    PETITIONER: DimensionScores
    RESPONDENT: DimensionScores
    reasons: NonEmptyStr
    record_ids_relied_on: list[NonEmptyStr]


class JudgeScorecard(StoredModel):
    judge: Literal["TEXTUALIST", "PURPOSIVIST", "PROCEDURALIST"]
    issue_scores: list[IssueScore] = Field(min_length=1)


class ThemisGlobalReport(StoredModel):
    """Shape fixed in Step 10; it never holds ground-truth fields (SPEC I3-1)."""

    consistency: dict[str, Any]
    rebuttal_depth: dict[str, Any]
    contradictions: list[dict[str, Any]]


class Aggregate(StoredModel):
    PETITIONER: float
    RESPONDENT: float


class IssueAlignment(StoredModel):
    """One framed issue: what the bench held against what the court held (SPEC G2)."""

    issue_id: IssueId
    bench: Upholds | None  # None when the bench was UNSTABLE on the issue
    real: Upholds
    driver: Literal["LAW", "EVIDENCE", "MIXED"]
    aligned: bool | None  # None when the bench did not decide the issue


class Evaluation(StoredModel):
    # None when the real outcome is MIXED (SPEC I2) or the bench verdict is UNSTABLE (D-051).
    winner_matches_real: bool | None
    # Share of compared issues the bench decided as the court did. None when no issue could be compared.
    issue_alignment: UnitScore | None
    # Added with the evaluator (Step 12); defaults keep earlier documents valid.
    real_overall: Literal["PETITIONER", "RESPONDENT", "MIXED"] | None = None
    issues: list[IssueAlignment] = Field(default_factory=list)


class Session(StoredModel):
    id: NonEmptyStr = Field(alias="_id")
    case_id: CaseId
    split: Split
    state: SessionState
    versions: VersionStamp
    config: SessionConfig
    themis_global: ThemisGlobalReport | None
    judge_scorecards: list[JudgeScorecard]
    aggregate: Aggregate | None
    winner: Literal["PETITIONER", "RESPONDENT", "TIE", "UNSTABLE"] | None
    evaluation: Evaluation | None
    lessons_written: list[NonEmptyStr]
    # The bench's reasoned decision (D-048). Defaults keep documents written before Step 11 valid.
    judge_decisions: list[JudgeDecision] = Field(default_factory=list)
    bench: BenchVerdict | None = None

    @model_validator(mode="after")
    def _fields_match_state(self) -> Session:
        has_verdict = self.winner is not None and self.aggregate is not None
        if has_verdict != (self.state in UNSEALED_STATES):
            raise ValueError(f"winner and aggregate are set exactly when the verdict is recorded (state {self.state})")
        if self.evaluation is not None and self.state not in EVALUATED_STATES:
            raise ValueError("evaluation is written only after the evaluator has run")
        if self.bench is not None:
            expected = self.bench.winner or "UNSTABLE"
            if self.winner != expected:
                raise ValueError(f"winner must mirror the bench verdict ({expected}), not {self.winner}")
            if not self.judge_decisions:
                raise ValueError("a bench verdict is stored with the judge decisions it came from")
        elif self.judge_decisions:
            raise ValueError("judge decisions are stored only with the bench verdict")
        return self


def aggregate_from(bench: BenchVerdict) -> Aggregate:
    """The SPEC H4 `aggregate` for a bench verdict: the secondary advocacy score, 0 for a side nobody scored."""
    scores = bench.advocacy or {}
    return Aggregate.model_validate({side: scores.get(side, 0.0) for side in SIDES})
