"""Experience-memory lesson (DATA_FORMATS §5, SPEC F, I3-5)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from lexarena.schemas.base import NonEmptyStr, SourceParas, StoredModel, UnitScore, UpperCode

LessonType = Literal["ADVOCACY", "LEGAL_RULE", "PROCEDURAL_ERROR"]
MemoryKind = Literal["LAWYER", "JUDGE"]
MAX_SEVERITY = 5  # literal-ok: DATA_FORMATS §5 defines severity as 1 to 5


class Provenance(StoredModel):
    case_id: NonEmptyStr
    issue_ids: list[NonEmptyStr] = Field(min_length=1)
    source_paras: SourceParas


class Lesson(StoredModel):
    lesson_id: NonEmptyStr
    lesson_type: LessonType
    memory: MemoryKind
    party_status: UpperCode | None
    statute_ids: list[NonEmptyStr]
    error_code: UpperCode | None
    trigger: NonEmptyStr
    lesson: NonEmptyStr
    provenance: Provenance
    driver: Literal["LAW"]  # EVIDENCE-driven mismatches never produce lessons (SPEC F5)
    severity: int = Field(ge=1, le=MAX_SEVERITY)
    frequency: int = Field(ge=1)
    confidence: UnitScore
    last_retrieved_case_seq: int = Field(ge=0)
    status: Literal["ACTIVE", "RETIRED"]
    created_in_run: NonEmptyStr
    # The reward of the case that last used it (SPEC F4: confidence rises when the next use does at least as well).
    last_reward: UnitScore | None = None
    # D-111: the law the source case saw, per statute (`versioning.statute_version`), and the year it was decided. A
    # lesson is pinned only into a case that sees the same version of each statute it shares; the year is for the owner
    # and never shown to an agent. Lessons written before D-111 carry neither and match every version.
    law_versions: dict[str, str] = Field(default_factory=dict)
    source_year: int | None = None
    source_review: Literal["OWNER", "CLAUDE_TRIAGE"] | None = None  # D-114: which review let the source case teach
    mistake: str | None = None  # D-113: the reflection checklist's kind of mistake (None before D-113)

    @model_validator(mode="after")
    def _routing(self) -> Lesson:
        # ARCHITECTURE §6 and SPEC I3-5: which lesson type may live in which memory.
        if self.memory == "JUDGE" and self.lesson_type != "LEGAL_RULE":
            raise ValueError("judge memory takes LEGAL_RULE lessons only (SPEC I3-5)")
        if self.lesson_type == "ADVOCACY" and self.memory != "LAWYER":
            raise ValueError("ADVOCACY lessons go to lawyer memory")
        if self.memory == "LAWYER" and self.party_status is None:
            raise ValueError("lawyer lessons are keyed by party_status (SPEC I2)")
        if self.memory == "JUDGE" and self.party_status is not None:
            raise ValueError("judge lessons carry no party_status")
        if self.lesson_type == "PROCEDURAL_ERROR" and self.error_code is None:
            raise ValueError("PROCEDURAL_ERROR lessons are tied to an error code")
        return self
