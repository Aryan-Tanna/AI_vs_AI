"""Objects the clerk exchanges with its models (BUILD_PLAN Step 6, D-056). Never stored as such: they become the
case, the ground truth and the judgment text after code checks them."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from lexarena.schemas.base import NonEmptyStr, StoredModel
from lexarena.schemas.judgment import JudgmentPart

EntityKind = Literal["PERSON", "COMPANY", "BANK", "AUTHORITY", "OTHER"]


class NamedEntity(StoredModel):
    """A named person or organisation in the judgment (not a court, not a statute), with every other form of its
    name the judgment uses."""

    name: NonEmptyStr
    variants: list[NonEmptyStr]
    kind: EntityKind


class EntityList(StoredModel):
    entities: list[NamedEntity]


class AssignedPseudonym(StoredModel):
    entity: NamedEntity
    pseudonym: NonEmptyStr


class ParagraphLabel(StoredModel):
    para_id: str = Field(pattern=r"^P[1-9]\d*$")
    part: JudgmentPart


class RouteResult(StoredModel):
    labels: list[ParagraphLabel]


class RecordFactIds(StoredModel):
    record_fact_ids: list[str]


class CourtSentence(StoredModel):
    """A sentence from a reasoning paragraph that only restates the record (D-058); it keeps its paragraph."""

    para_id: str = Field(pattern=r"^P[1-9]\d*$")
    sentence_id: str = Field(pattern=r"^P[1-9]\d*\.S[1-9]\d*$")
    text: NonEmptyStr
