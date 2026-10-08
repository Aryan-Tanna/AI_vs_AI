"""A run: a frozen-version pass over cases in date order, one at a time (BUILD_PLAN Step 13; ARCHITECTURE §7;
SPEC G1, I3-10; D-073).

The ledger is the run's checkpoint: it is written after every stage, so a run stopped by a quota, a crash or the
operator resumes at the first unfinished stage of the first unfinished case. A FAILED case stops the run: in a learning
run, later cases must not run on memory that skipped one (SPEC I3-10).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, get_args

from pydantic import Field, model_validator

from lexarena.schemas.base import NonEmptyStr, StoredModel
from lexarena.schemas.case import CaseId, Split

Stage = Literal["SESSION", "BASELINE", "EVALUATE", "REFLECT"]
STAGES: tuple[Stage, ...] = get_args(Stage)
MemoryMode = Literal["LEARN", "FROZEN", "EMPTY"]
StageStatus = Literal["PENDING", "DONE", "FAILED", "SKIPPED", "NOT_BUILT", "DRY"]
FINISHED: frozenset[str] = frozenset({"DONE", "SKIPPED", "NOT_BUILT", "DRY"})


class StageRecord(StoredModel):
    stage: Stage
    status: StageStatus
    attempts: int = Field(ge=0)
    started_at: datetime | None
    finished_at: datetime | None
    detail: str | None  # the command run, why it was skipped, or the error class and message
    outputs: dict[str, str]  # e.g. session_id, written files


class CaseJob(StoredModel):
    seq: int = Field(ge=1)
    case_id: CaseId
    split: Split
    # The run order key. Held by the run manager (an orchestrator-side role) and never put into a prompt (R-018).
    decided_on: date
    stages: list[StageRecord]
    memory_before: NonEmptyStr | None
    memory_after: NonEmptyStr | None

    def record(self, stage: Stage) -> StageRecord:
        return next(r for r in self.stages if r.stage == stage)

    @property
    def finished(self) -> bool:
        return all(r.status in FINISHED for r in self.stages)


class RunManifest(StoredModel):
    run_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    created_at: datetime
    mode: MemoryMode
    ablations: list[NonEmptyStr]
    stages: list[Stage] = Field(min_length=1)
    git_sha: NonEmptyStr
    config_version: NonEmptyStr
    config_sha256: NonEmptyStr
    dry_run: bool
    # Dev runs before the owner approves the persona prompts: every judge decision is stamped unapproved (D-071).
    allow_draft_personas: bool = False


class RunLedger(StoredModel):
    manifest: RunManifest
    status: Literal["PLANNED", "RUNNING", "PAUSED", "FAILED", "COMPLETE"]
    pause_reason: str | None
    jobs: list[CaseJob]

    @model_validator(mode="after")
    def _date_order(self) -> RunLedger:
        keys = [(j.decided_on, j.case_id) for j in self.jobs]
        if keys != sorted(keys):
            raise ValueError("a run's cases are in date order (ARCHITECTURE §7)")
        if [j.seq for j in self.jobs] != list(range(1, len(self.jobs) + 1)):
            raise ValueError("jobs are numbered 1..n in run order")
        if len({j.case_id for j in self.jobs}) != len(self.jobs):
            raise ValueError("a case runs at most once per run")
        return self
