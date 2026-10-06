"""`cases` collection (SPEC H1): the agent view of a case plus build information.

Two views of the same stored document:

- `Case` is the whole document (build block, split, agent view including `simulation_date`). Only the
  clerk, the orchestrator and post-verdict components read it.
- `AgentCaseView` is what lawyers, THEMIS and judges receive: the agent view without `simulation_date`,
  and nothing from `build` or `split`. The decision date and build data help a model recognise the real
  case, so they never reach a prompt (SPEC H1 "stripped before prompting"; D-035). Retrieval applies the
  date cut-off and exclusion list server-side from `Case`.

Structural cross-references (every fact, exhibit, party and issue ID that is referred to exists) are
checked here, because a dangling ID would let an agent cite a record item that does not exist.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from lexarena.schemas.base import SIDES, NonEmptyStr, Side, SourceParas, StoredModel, UpperCode

FactId = Annotated[str, StringConstraints(pattern=r"^[FC]\d+$")]
StipulatedId = Annotated[str, StringConstraints(pattern=r"^F\d+$")]
ContestedId = Annotated[str, StringConstraints(pattern=r"^C\d+$")]
ExhibitId = Annotated[str, StringConstraints(pattern=r"^EX-\d+$")]
AmountId = Annotated[str, StringConstraints(pattern=r"^AM\d+$")]
IssueId = Annotated[str, StringConstraints(pattern=r"^I\d+$")]
CaseId = Annotated[str, StringConstraints(pattern=r"^\S+$", min_length=1)]

Split = Literal["DEV", "TRAIN", "VALIDATION", "TEST"]
SimulationSide = Literal["PETITIONER", "RESPONDENT", "PROFORMA"]
AgentName = Literal["LEX_P", "LEX_D", "NONE"]
AGENT_FOR_SIDE: dict[str, str] = {"PETITIONER": "LEX_P", "RESPONDENT": "LEX_D", "PROFORMA": "NONE"}


# ---------------------------------------------------------------- build (never shown to agents)


class ExtractionFlag(StoredModel):
    code: UpperCode
    detail: NonEmptyStr
    resolution: NonEmptyStr


class Build(StoredModel):
    source_forum: Literal["NCLT", "NCLAT"]
    evidence_dependency: Literal["LAW_ONLY", "MIXED", "EVIDENCE_DECIDED"]
    issues_source: Literal["FRAMED_BY_COURT", "DERIVED_FROM_SUBMISSIONS"]
    memorization_probe: Literal["NOT_IDENTIFIED", "IDENTIFIED"]
    excluded_precedent_ids: list[NonEmptyStr]
    extraction_flags: list[ExtractionFlag]
    human_reviewed: bool
    clerk_version: NonEmptyStr


# ---------------------------------------------------------------- agent view


class KeyDate(StoredModel):
    label: UpperCode
    date: date
    fact_id: FactId


class PromptMetadata(StoredModel):
    forum: Literal["NCLT", "NCLAT"]
    proceeding_type: UpperCode
    statutes_invoked: list[NonEmptyStr]
    key_dates: list[KeyDate]


class CaseMetadata(PromptMetadata):
    simulation_date: date


class Party(StoredModel):
    party_id: NonEmptyStr
    pseudonym: NonEmptyStr
    status: UpperCode
    simulation_side: SimulationSide
    appeal_position: UpperCode | None
    represented_by_agent: AgentName
    substituted_from: NonEmptyStr | None

    @model_validator(mode="after")
    def _agent_matches_side(self) -> Party:
        # SPEC I2: LEX-P argues the party seeking relief, LEX-D the opposing side; PROFORMA has no agent.
        if self.represented_by_agent != AGENT_FOR_SIDE[self.simulation_side]:
            raise ValueError(
                f"party {self.party_id}: side {self.simulation_side} must be represented by "
                f"{AGENT_FOR_SIDE[self.simulation_side]}, not {self.represented_by_agent}"
            )
        return self


class StipulatedFact(StoredModel):
    fact_id: StipulatedId
    text: NonEmptyStr
    source_paras: SourceParas


class ContestedFact(StoredModel):
    fact_id: ContestedId
    question: NonEmptyStr
    petitioner_version: NonEmptyStr
    respondent_version: NonEmptyStr
    source_paras: SourceParas


class Exhibit(StoredModel):
    exhibit_id: ExhibitId
    title: NonEmptyStr
    filed_by: NonEmptyStr
    known_contents: list[NonEmptyStr]
    contents_beyond_known: Literal["UNKNOWN"]
    authenticity: Literal["PRESUMED", "DISPUTED"]
    # Not in the H1 example; SPEC I3-8 requires source paragraphs for exhibit contents (I3 wins; D-035).
    source_paras: SourceParas


class Amount(StoredModel):
    amount_id: AmountId
    label: UpperCode
    value_inr: int | float = Field(ge=0)
    date: date | None
    party_id: NonEmptyStr | None
    fact_id: FactId


class Record(StoredModel):
    stipulated_facts: list[StipulatedFact]
    contested_facts: list[ContestedFact]
    exhibits: list[Exhibit]
    amounts: list[Amount]


class ProceduralStep(StoredModel):
    step: int = Field(ge=1)
    date: date
    forum: NonEmptyStr
    event: NonEmptyStr
    fact_id: FactId


class LowerForumOrder(StoredModel):
    exists: bool
    forum: NonEmptyStr | None
    result: UpperCode | None
    directions: list[NonEmptyStr]
    reasons_summary: NonEmptyStr | None
    ex_parte: bool | None

    @model_validator(mode="after")
    def _empty_unless_exists(self) -> LowerForumOrder:
        if not self.exists and (self.forum or self.result or self.directions or self.reasons_summary):
            raise ValueError("lower_forum_order has content but exists is false")
        if self.exists and (self.forum is None or self.result is None):
            raise ValueError("an existing lower_forum_order needs forum and result")
        return self


class FramedIssue(StoredModel):
    issue_id: IssueId
    question: NonEmptyStr
    statutes: list[NonEmptyStr]
    raised_by: Literal["PETITIONER", "RESPONDENT", "COURT"]


class ReliefsSought(StoredModel):
    PETITIONER: list[NonEmptyStr]
    RESPONDENT: list[NonEmptyStr]


class OpeningGround(StoredModel):
    issue_id: IssueId
    ground: NonEmptyStr


class OpeningPositions(StoredModel):
    PETITIONER: list[OpeningGround]
    RESPONDENT: list[OpeningGround]

    def for_side(self, side: Side) -> list[OpeningGround]:
        return self.PETITIONER if side == "PETITIONER" else self.RESPONDENT


def _unique(ids: list[str], what: str) -> set[str]:
    dupes = sorted(i for i, n in Counter(ids).items() if n > 1)
    if dupes:
        raise ValueError(f"duplicate {what}: {dupes}")
    return set(ids)


class _AgentViewFields(StoredModel):
    parties: list[Party]
    factual_background: NonEmptyStr
    record: Record
    procedural_history: list[ProceduralStep]
    lower_forum_order: LowerForumOrder
    framed_issues: list[FramedIssue] = Field(min_length=1)
    reliefs_sought: ReliefsSought
    opening_positions: OpeningPositions
    presumptions: list[NonEmptyStr]

    def _check_references(self, key_dates: list[KeyDate]) -> None:
        r = self.record
        facts = _unique([f.fact_id for f in r.stipulated_facts] + [c.fact_id for c in r.contested_facts], "fact IDs")
        _unique([e.exhibit_id for e in r.exhibits], "exhibit IDs")
        _unique([a.amount_id for a in r.amounts], "amount IDs")
        parties = _unique([p.party_id for p in self.parties], "party IDs")
        issues = _unique([i.issue_id for i in self.framed_issues], "issue IDs")

        refs: list[tuple[str, str | None, set[str]]] = []
        refs += [(f"amount {a.amount_id}.fact_id", a.fact_id, facts) for a in r.amounts]
        refs += [(f"amount {a.amount_id}.party_id", a.party_id, parties) for a in r.amounts]
        refs += [(f"key_date {d.label}.fact_id", d.fact_id, facts) for d in key_dates]
        refs += [(f"procedural step {s.step}.fact_id", s.fact_id, facts) for s in self.procedural_history]
        refs += [(f"exhibit {e.exhibit_id}.filed_by", e.filed_by, parties) for e in r.exhibits]
        refs += [(f"party {p.party_id}.substituted_from", p.substituted_from, parties) for p in self.parties]
        for side in SIDES:
            refs += [
                (f"opening_positions.{side}.issue_id", g.issue_id, issues)
                for g in self.opening_positions.for_side(side)
            ]
        dangling = [f"{where} -> {ref}" for where, ref, valid in refs if ref is not None and ref not in valid]
        if dangling:
            raise ValueError(f"dangling references: {dangling}")

        sides = {p.simulation_side for p in self.parties}
        if not {"PETITIONER", "RESPONDENT"} <= sides:
            raise ValueError("a case needs at least one PETITIONER and one RESPONDENT party")


class AgentView(_AgentViewFields):
    """`cases.agent_view` as stored."""

    metadata: CaseMetadata

    @model_validator(mode="after")
    def _references(self) -> AgentView:
        self._check_references(self.metadata.key_dates)
        return self


class AgentCaseView(_AgentViewFields):
    """What lawyers, THEMIS and judges receive: no simulation_date, no build, no split (D-035)."""

    case_id: CaseId
    metadata: PromptMetadata

    @model_validator(mode="after")
    def _references(self) -> AgentCaseView:
        self._check_references(self.metadata.key_dates)
        return self


class Case(StoredModel):
    id: CaseId = Field(alias="_id")
    split: Split
    build: Build
    agent_view: AgentView
