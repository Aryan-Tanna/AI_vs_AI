"""`sessions` collection (SPEC H4) and the session state machine.

The state is what unseals ground truth: `case_ground_truth` is readable only while the session is in
an `UNSEALED_STATES` state, and only by the evaluator and the reflection engine (CLAUDE.md §10).
States move forward only, along `TRANSITIONS`; nothing returns to a sealed state once unsealed.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from lexarena.schemas.base import NonEmptyStr, StoredModel, UnitScore
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


class DimensionScores(StoredModel):
    accuracy: UnitScore
    consistency: UnitScore
    rebuttal: UnitScore
    grounding: UnitScore


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


class Evaluation(StoredModel):
    winner_matches_real: bool | None  # None when the real outcome is MIXED (SPEC I2)
    issue_alignment: UnitScore


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
    winner: Literal["PETITIONER", "RESPONDENT", "TIE"] | None
    evaluation: Evaluation | None
    lessons_written: list[NonEmptyStr]

    @model_validator(mode="after")
    def _fields_match_state(self) -> Session:
        has_verdict = self.winner is not None and self.aggregate is not None
        if has_verdict != (self.state in UNSEALED_STATES):
            raise ValueError(f"winner and aggregate are set exactly when the verdict is recorded (state {self.state})")
        if self.evaluation is not None and self.state not in EVALUATED_STATES:
            raise ValueError("evaluation is written only after the evaluator has run")
        return self
