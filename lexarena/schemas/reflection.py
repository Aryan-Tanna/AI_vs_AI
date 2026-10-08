"""What the reflection model returns (BUILD_PLAN Step 12; SPEC F1-F7; D-077). Code turns a candidate into a `Lesson`
only after every rule is checked (lexarena/reflection/filters.py)."""

from __future__ import annotations

from typing import Literal

from lexarena.schemas.base import StoredModel

LessonFor = Literal["PETITIONER", "RESPONDENT", "BENCH"]


class LessonCandidate(StoredModel):
    lesson_type: Literal["ADVOCACY", "LEGAL_RULE", "PROCEDURAL_ERROR"]
    for_whom: LessonFor  # a side's advocate (lawyer memory, keyed by that side's party status) or the bench
    statute_ids: list[str]
    error_code: str | None
    trigger: str
    lesson: str
    issue_ids: list[str]
    source_paras: list[str]
    severity: int


class LessonCandidates(StoredModel):
    lessons: list[LessonCandidate]


class CompareVerdict(StoredModel):
    relation: Literal["SAME", "OPPOSITE", "DIFFERENT"]
