"""Objects the clerk exchanges with its models (BUILD_PLAN Step 6, D-056). Never stored as such: they become the
case, the ground truth and the judgment text after code checks them."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from lexarena.schemas.base import NonEmptyStr, StoredModel
from lexarena.schemas.case import (
    FramedIssue,
    KeyDate,
    LowerForumOrder,
    OpeningPositions,
    ProceduralStep,
    Record,
    ReliefsSought,
)
from lexarena.schemas.judgment import JudgmentPart

EntityKind = Literal["PERSON", "COMPANY", "BANK", "AUTHORITY", "OTHER"]


class NamedEntity(StoredModel):
    """A named person or organisation in the judgment (not a court, not a statute), with every other form of its
    name the judgment uses, and its place in the cause title if it is a party there (APPELLANT, RESPONDENT_1 ...)."""

    name: NonEmptyStr
    variants: list[NonEmptyStr]
    kind: EntityKind
    cause_title_role: str | None = Field(pattern=r"^[A-Z][A-Z0-9_]*$")


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


class PartyDraft(StoredModel):
    party_id: str = Field(pattern=r"^[AR][1-9]\d*$")
    pseudonym: NonEmptyStr
    status: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    simulation_side: Literal["PETITIONER", "RESPONDENT", "PROFORMA"]
    appeal_position: str | None = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    substituted_from: str | None


class AgentViewDraft(StoredModel):
    """What the agent-view extractor returns. Code adds the forum, the decision date, the presumptions and which
    agent argues each side, then validates the whole as an `AgentView` (D-056)."""

    proceeding_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    statutes_invoked: list[NonEmptyStr]
    key_dates: list[KeyDate]
    parties: list[PartyDraft]
    factual_background: NonEmptyStr
    record: Record
    procedural_history: list[ProceduralStep]
    lower_forum_order: LowerForumOrder
    framed_issues: list[FramedIssue] = Field(min_length=1)
    reliefs_sought: ReliefsSought
    opening_positions: OpeningPositions
