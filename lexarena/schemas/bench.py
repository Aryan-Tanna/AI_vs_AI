"""The bench's reasoned decision (D-048, D-051; ARCHITECTURE §5; BUILD_PLAN Step 11).

Each persona decides every framed issue twice, once with each side's submissions presented first. One presentation is
a `JudgeOpinion`: per issue, a finding, the governing rule (statute or precedent IDs), the application to record IDs,
the conclusion and the side whose position it upholds; then the overall result, with the advocacy scores (SPEC E1) kept
as the secondary measure.

`JudgeDecision` folds a persona's two opinions together. A persona decides an issue, or the case, only if both
presentation orders agree; otherwise it abstains on it. `BenchVerdict` is the majority of the deciding personas, with
dissent recorded. The advocacy score breaks only an even split of deciding personas; with fewer deciding personas than
`judging.min_deciding_judges` the verdict is UNSTABLE and the score never decides it (D-051).

Sides are named PETITIONER and RESPONDENT here (SPEC I2). Judges never see agent or model names; their prompts call the
sides "Petitioner's counsel" and "Respondent's counsel" (SPEC E1).
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Literal, get_args

from pydantic import Field, model_validator

from lexarena.schemas.base import SIDES, NonEmptyStr, Side, StoredModel, UnitScore
from lexarena.schemas.case import IssueId

Persona = Literal["TEXTUALIST", "PURPOSIVIST", "PROCEDURALIST"]
PERSONAS: tuple[Persona, ...] = get_args(Persona)
PresentationOrder = Literal["PETITIONER_FIRST", "RESPONDENT_FIRST"]
ORDERS: tuple[PresentationOrder, ...] = get_args(PresentationOrder)
Upholds = Literal["PETITIONER", "RESPONDENT", "NEITHER"]
AbstainReason = Literal["ORDER_SWAP_DISAGREEMENT", "INVALID_OPINION"]


def _no_duplicates(ids: list[str], what: str) -> None:
    dupes = sorted(i for i, n in Counter(ids).items() if n > 1)
    if dupes:
        raise ValueError(f"duplicate {what}: {dupes}")


class DimensionScores(StoredModel):
    """SPEC E1 advocacy dimensions, each in [0, 1]; weights live in config (`judging.weights`)."""

    accuracy: UnitScore
    consistency: UnitScore
    rebuttal: UnitScore
    grounding: UnitScore


class IssueDecision(StoredModel):
    issue_id: IssueId
    finding: NonEmptyStr
    # Statute IDs (Law DB) or precedent UIDs the decision rests on; checked against what the judge was shown.
    governing_rule_ids: list[NonEmptyStr] = Field(min_length=1)
    # Record items (F, C, EX, AM) the rule is applied to. May be empty for a pure question of law.
    record_ids: list[NonEmptyStr]
    application: NonEmptyStr
    conclusion: NonEmptyStr
    upholds: Upholds


class IssueAdvocacy(StoredModel):
    issue_id: IssueId
    PETITIONER: DimensionScores
    RESPONDENT: DimensionScores


class JudgeOpinion(StoredModel):
    """One persona's decision under one presentation order, after validation."""

    order: PresentationOrder
    issue_decisions: list[IssueDecision] = Field(min_length=1)
    overall_result: Side
    overall_reasons: NonEmptyStr
    advocacy: list[IssueAdvocacy] = Field(min_length=1)
    revised: bool  # the validator sent it back once (ARCHITECTURE §5: one revision)
    # Problems the one revision did not fix. An opinion with any is INVALID and its persona abstains.
    problems: list[NonEmptyStr]

    @model_validator(mode="after")
    def _issues_match(self) -> JudgeOpinion:
        decided = [d.issue_id for d in self.issue_decisions]
        scored = [a.issue_id for a in self.advocacy]
        _no_duplicates(decided, "issue decisions")
        _no_duplicates(scored, "advocacy issues")
        if set(decided) != set(scored):
            raise ValueError("advocacy must score exactly the issues the opinion decides")
        return self

    @property
    def valid(self) -> bool:
        return not self.problems


class JudgeIssueResult(StoredModel):
    issue_id: IssueId
    status: Literal["DECIDED", "ABSTAINED"]
    upholds: Upholds | None

    @model_validator(mode="after")
    def _upholds_iff_decided(self) -> JudgeIssueResult:
        if (self.status == "DECIDED") != (self.upholds is not None):
            raise ValueError("upholds is set exactly when the issue is DECIDED")
        return self


class JudgeDecision(StoredModel):
    """A persona's two opinions and what follows from them."""

    judge: Persona
    # Which persona prompt produced it, and whether that exact text was APPROVED (CLAUDE.md §4.8) when it ran.
    persona_prompt: NonEmptyStr
    persona_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    persona_approved: bool
    opinions: list[JudgeOpinion] = Field(min_length=len(ORDERS), max_length=len(ORDERS))
    status: Literal["DECIDED", "ABSTAINED"]
    result: Side | None
    abstain_reason: AbstainReason | None
    issue_results: list[JudgeIssueResult]
    # Largest |weighted score in one order - weighted score in the other| over issues and sides (SPEC E1).
    order_swap_gap: UnitScore | None
    advocacy: dict[Side, UnitScore] | None  # the persona's weighted score per side, both orders and all issues

    @model_validator(mode="after")
    def _consistent(self) -> JudgeDecision:
        if sorted(o.order for o in self.opinions) != sorted(ORDERS):
            raise ValueError("a judge decision holds one opinion per presentation order")
        if (self.status == "DECIDED") != (self.result is not None):
            raise ValueError("result is set exactly when the judge DECIDED")
        if (self.status == "ABSTAINED") != (self.abstain_reason is not None):
            raise ValueError("abstain_reason is set exactly when the judge ABSTAINED")
        if self.result is not None and any(o.overall_result != self.result for o in self.opinions):
            raise ValueError("a judge decides only a result both presentation orders reached")
        _no_duplicates([r.issue_id for r in self.issue_results], "issue results")
        return self


class BenchIssueFinding(StoredModel):
    issue_id: IssueId
    status: Literal["DECIDED", "UNSTABLE"]
    upholds: Upholds | None
    votes: dict[Upholds, int]
    deciding_judges: list[Persona]
    dissenting_judges: list[Persona]

    @model_validator(mode="after")
    def _upholds_iff_decided(self) -> BenchIssueFinding:
        if (self.status == "DECIDED") != (self.upholds is not None):
            raise ValueError("upholds is set exactly when the bench DECIDED the issue")
        return self


class BenchVerdict(StoredModel):
    status: Literal["DECIDED", "UNSTABLE"]
    winner: Side | None
    decided_by: Literal["MAJORITY", "TIE_BREAK"] | None
    unstable_reason: Literal["TOO_FEW_DECIDING_JUDGES", "UNBROKEN_TIE"] | None
    votes: dict[Side, int]
    deciding_judges: list[Persona]
    abstaining_judges: list[Persona]
    dissenting_judges: list[Persona]
    issue_findings: list[BenchIssueFinding] = Field(min_length=1)
    # Secondary measure (D-048): mean weighted advocacy score per side over every valid opinion. None when no
    # persona produced a valid opinion.
    advocacy: dict[Side, UnitScore] | None

    @model_validator(mode="after")
    def _consistent(self) -> BenchVerdict:
        decided = self.status == "DECIDED"
        if decided != (self.winner is not None) or decided != (self.decided_by is not None):
            raise ValueError("winner and decided_by are set exactly when the verdict is DECIDED")
        if decided == (self.unstable_reason is not None):
            raise ValueError("unstable_reason is set exactly when the verdict is UNSTABLE")
        if set(self.votes) != set(SIDES):
            raise ValueError("votes counts both sides")
        if self.decided_by == "TIE_BREAK" and self.votes["PETITIONER"] != self.votes["RESPONDENT"]:
            raise ValueError("the advocacy score breaks only an even split of deciding judges (D-051)")
        if self.decided_by == "MAJORITY" and self.winner is not None:
            loser: Side = "RESPONDENT" if self.winner == "PETITIONER" else "PETITIONER"
            if self.votes[self.winner] <= self.votes[loser]:
                raise ValueError("a MAJORITY winner needs more deciding votes than the other side")
        overlap = set(self.deciding_judges) & set(self.abstaining_judges)
        if overlap:
            raise ValueError(f"a judge cannot both decide and abstain: {sorted(overlap)}")
        _no_duplicates([f.issue_id for f in self.issue_findings], "bench issue findings")
        return self


# ---------------------------------------------------------------- what the judge model returns
#
# Plain strings and lists only (strict JSON-schema modes refuse free-form maps and regex-heavy keys). Code turns a
# draft into a `JudgeOpinion` after checking every ID against what the judge was shown (judges/validate.py).


class IssueDecisionDraft(StoredModel):
    issue_id: str
    finding: str
    governing_rule_ids: list[str]
    record_ids: list[str]
    application: str
    conclusion: str
    upholds: Upholds


class IssueAdvocacyDraft(StoredModel):
    issue_id: str
    petitioner: DimensionScores
    respondent: DimensionScores


class OpinionDraft(StoredModel):
    issue_decisions: list[IssueDecisionDraft]
    overall_result: Side
    overall_reasons: str
    advocacy: list[IssueAdvocacyDraft]


# ---------------------------------------------------------------- persona prompt approval (CLAUDE.md §4.8)


class PersonaApproval(StoredModel):
    """`review/judge_personas/<PERSONA>.json`: the owner's decision on one persona prompt's exact text.

    The approval is bound to the text's SHA-256, so an edited prompt is a new DRAFT, like a STALE predicate.
    """

    persona: Persona
    prompt_id: NonEmptyStr
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["DRAFT", "APPROVED", "REJECTED"]
    decided_by: NonEmptyStr | None
    decided_on: date | None
    note: NonEmptyStr | None

    @model_validator(mode="after")
    def _decided(self) -> PersonaApproval:
        undecided = self.status == "DRAFT"
        if undecided != (self.decided_by is None) or undecided != (self.decided_on is None):
            raise ValueError("decided_by and decided_on are set exactly when the draft is APPROVED or REJECTED")
        return self
