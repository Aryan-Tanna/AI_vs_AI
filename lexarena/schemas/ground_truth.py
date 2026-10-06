"""`case_ground_truth` (SPEC H2): sealed until the verdict. Lives in its own database (D-024)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from lexarena.schemas.base import NonEmptyStr, SourceParas, StoredModel
from lexarena.schemas.case import CaseId, IssueId

Forum = Literal["SC", "NCLAT", "NCLT", "HC"]
Favours = Literal["PETITIONER", "RESPONDENT", "NEITHER"]


class Citation(StoredModel):
    case_number: NonEmptyStr
    arising_from: NonEmptyStr | None
    bench: list[NonEmptyStr]
    decision_date: date
    source_title: NonEmptyStr


class AuthorityCited(StoredModel):
    name: NonEmptyStr
    precedent_id: NonEmptyStr | None
    forum: Forum
    proposition: NonEmptyStr


class Submission(StoredModel):
    issue_id: IssueId
    contention: NonEmptyStr
    statutes_cited: list[NonEmptyStr]
    authorities_cited: list[AuthorityCited]
    source_paras: SourceParas


class RealSubmissions(StoredModel):
    PETITIONER: list[Submission]
    RESPONDENT: list[Submission]


class StatutoryAnalysis(StoredModel):
    statute_id: NonEmptyStr
    interpretation: NonEmptyStr
    interacts_with: list[NonEmptyStr]
    source_paras: SourceParas


class PrecedentAnalysis(StoredModel):
    name: NonEmptyStr
    precedent_id: NonEmptyStr | None
    forum: Forum
    bench_strength: int | None = Field(ge=1)
    cited_by: Literal["PETITIONER", "RESPONDENT", "COURT"]
    treatment: Literal["FOLLOWED", "APPLIED", "DISTINGUISHED", "NOT_FOLLOWED", "DOUBTED", "NOTED"]
    proposition: NonEmptyStr
    later_history: NonEmptyStr | None
    source_paras: SourceParas


class IssueFinding(StoredModel):
    issue_id: IssueId
    favours: Favours
    driver: Literal["LAW", "EVIDENCE", "MIXED"]
    finding: NonEmptyStr
    reasoning: NonEmptyStr
    test_applied: NonEmptyStr
    decisive_points: list[NonEmptyStr]
    authorities_relied_on: list[NonEmptyStr]
    source_paras: SourceParas


class ReliefOutcome(StoredModel):
    relief: NonEmptyStr
    sought_by: Literal["PETITIONER", "RESPONDENT"]
    outcome: Literal["GRANTED", "REFUSED", "PARTLY_GRANTED", "MODIFIED"]


class Conclusion(StoredModel):
    disposition: Literal["ALLOWED", "DISMISSED", "PARTLY_ALLOWED", "DISPOSED_WITH_DIRECTIONS", "REMANDED", "SET_ASIDE"]
    reliefs: list[ReliefOutcome]
    directions: list[NonEmptyStr]
    costs: NonEmptyStr | None
    overall_favours: Literal["PETITIONER", "RESPONDENT", "MIXED"]


class CaseGroundTruth(StoredModel):
    id: CaseId = Field(alias="_id")
    access: Literal["SEALED_UNTIL_VERDICT"]
    citation: Citation
    anonymization_map: dict[NonEmptyStr, NonEmptyStr]
    real_submissions: RealSubmissions
    statutory_analysis: list[StatutoryAnalysis]
    precedent_analysis: list[PrecedentAnalysis]
    issue_findings: list[IssueFinding]
    conclusion: Conclusion
