"""Public case DB record schema (CLAUDE.md §6.6). One case = three records sharing `case_uid`:

  PublicUnspoiled   -> public_db/unspoiled.jsonl     what advocates and judges see (runtime)
  PublicGroundTruth -> public_db/ground_truth.jsonl  the real NCLAT decision (sealed; evaluator + train reflection)
  PublicManifest    -> public_db/manifest.jsonl      provenance, real names, split, QA (never sent to an LLM)

Single-file rules are enforced here; cross-file rules (issue coverage, anonymisation, leakage, splits) are in
scripts/validate_public_db.py. JSON Schema exports: scripts/export_schemas.py -> docs/schema/.
"""
import datetime as dt
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

SCHEMA_VERSION = "1.0"

# ---- enums (CLAUDE.md §6.3) -------------------------------------------------------------------------------

ProceedingType = Literal[
    "SEC7_ADMISSION", "SEC9_ADMISSION", "SEC10_ADMISSION", "SEC12A_WITHDRAWAL", "MORATORIUM_SEC14",
    "CLAIMS_VERIFICATION", "COC_CONSTITUTION", "RESOLUTION_PLAN_APPROVAL", "SEC29A_ELIGIBILITY", "LIQUIDATION",
    "AVOIDANCE_43_66", "SEC60_5_JURISDICTION", "APPEAL_LIMITATION_CONDONATION", "PERSONAL_GUARANTOR_95_100",
    "IP_DISCIPLINARY", "RECALL_REVIEW", "COMPANIES_ACT_241_242", "COMPANIES_ACT_STRIKE_OFF", "OTHER",
]
Role = Literal[
    "FINANCIAL_CREDITOR", "OPERATIONAL_CREDITOR", "SUSPENDED_DIRECTOR_PROMOTER", "SHAREHOLDER", "CORPORATE_DEBTOR",
    "RESOLUTION_PROFESSIONAL", "LIQUIDATOR", "RESOLUTION_APPLICANT", "COC", "STATUTORY_AUTHORITY",
    "WORKMEN_EMPLOYEES", "HOMEBUYERS", "PERSONAL_GUARANTOR", "IBBI", "OTHER",
]
Label = Literal["ALLOWED", "DISMISSED", "PARTLY_ALLOWED", "ALLOWED_REMANDED", "WITHDRAWN", "DISPOSED"]
Split = Literal["train", "dev", "test"]
DocName = Literal["JUDGMENT", "IMPUGNED"]
DatePrecision = Literal["DAY", "MONTH", "FY", "RANGE"]
PartyKind = Literal["COMPANY", "LLP", "BANK", "NBFC", "ARC", "INDIVIDUAL", "GOVERNMENT", "STATUTORY_BODY",
                    "RESOLUTION_PROFESSIONAL", "LIQUIDATOR", "COC", "OTHER"]
PlaceholderKind = Literal["APPLICATION", "PROCEEDING", "DOCUMENT", "PROPERTY", "OTHER"]
RecordDocKind = Literal["LOAN_AGREEMENT", "SANCTION_LETTER", "DEMAND_NOTICE", "INVOICE", "NOTICE_OF_DISPUTE",
                        "BALANCE_SHEET", "OTS_PROPOSAL", "ACKNOWLEDGMENT_LETTER", "APPLICATION", "REPLY",
                        "ORDER", "REPORT", "COMPILATION", "RESOLUTION_PLAN", "COC_MINUTES", "CLAIM_FORM",
                        "CORRESPONDENCE", "OTHER"]
AckKind = Literal["BALANCE_SHEET", "LETTER", "OTS", "PART_PAYMENT", "OTHER"]

TOKEN_RE = re.compile(r"\[[A-Z][A-Z0-9_]*\]")
Token = Annotated[str, StringConstraints(pattern=r"^\[[A-Z][A-Z0-9_]*\]$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---- shared pieces ------------------------------------------------------------------------------------------

class Src(_Strict):
    """Where a value comes from in the source PDF. Every fact carries at least one."""
    doc: DocName = "JUDGMENT"
    page: int = Field(ge=1)
    para: str | None = None


class SrcRequired(_Strict):
    src: list[Src] = Field(min_length=1)


# ---- unspoiled ----------------------------------------------------------------------------------------------

class Party(_Strict):
    token: Token
    kind: PartyKind
    side: Literal["APPELLANT", "RESPONDENT", "NON_PARTY"]
    role: Role | None = None
    description: str = Field(max_length=200, description="Neutral, non-identifying description")


class Placeholder(_Strict):
    """Tokens for applications, proceedings or documents whose numbers are removed (e.g. [ATTACHMENT_APPLICATION])."""
    token: Token
    kind: PlaceholderKind
    description: str = Field(max_length=200)


class ImpugnedOrder(SrcRequired):
    forum: Literal["NCLT", "IBBI", "OTHER"] = "NCLT"
    bench_city: str = Field(pattern=r"^[A-Z_]+$")
    date: dt.date
    application_type: str = Field(description="What was decided below, e.g. SEC7, SEC9, IA_REJECTION_OF_CLAIM")
    outcome_below: str = Field(description="e.g. ADMITTED, REJECTED, PLAN_APPROVED, APPLICATIONS_REJECTED")
    reasoning_summary: str = Field(description="Neutral summary of the NCLT's reasons")
    operative_part: str | None = None


class Event(SrcRequired):
    id: str = Field(pattern=r"^E\d+$")
    date: dt.date | None = None
    date_to: dt.date | None = None
    date_precision: DatePrecision = "DAY"
    event: str
    actor: Token | None = None
    conflict_ref: str | None = Field(None, description="typed_facts key holding conflicting values for this date")

    @model_validator(mode="after")
    def _range(self):
        if self.date_precision in ("FY", "RANGE") and (self.date is None or self.date_to is None):
            raise ValueError(f"{self.id}: {self.date_precision} needs date and date_to")
        if self.date and self.date_to and self.date_to < self.date:
            raise ValueError(f"{self.id}: date_to before date")
        return self


class TypedFact(_Strict):
    """A single value, or several conflicting values found in the record (never resolved by the pipeline)."""
    value: dt.date | int | float | str | None = None
    values: list[dt.date | int | float | str] | None = None
    conflict: bool = False
    ref: str | None = Field(None, pattern=r"^E\d+$", description="chronology event id")
    src: list[Src] = Field(default_factory=list)
    verified: bool = False

    @model_validator(mode="after")
    def _shape(self):
        if self.conflict:
            if not self.values or len(self.values) < 2 or self.value is not None:
                raise ValueError("conflict=True needs >= 2 `values` and no `value`")
        elif self.values is not None:
            raise ValueError("`values` is only for conflict=True")
        if (self.value is not None or self.values) and not (self.ref or self.src):
            raise ValueError("a non-null typed fact needs `ref` or `src`")
        return self


class Acknowledgment(_Strict):
    date: dt.date | None
    kind: AckKind
    ref: str | None = Field(None, pattern=r"^E\d+$")
    src: list[Src] = Field(min_length=1)


class TypedFacts(_Strict):
    """CLAUDE.md §6.2. Absent = unknown; null value = looked for and not on record."""
    date_of_default: TypedFact | None = None
    date_of_npa: TypedFact | None = None
    demand_notice_delivery: TypedFact | None = None
    notice_of_dispute_date: TypedFact | None = None
    nclt_filing_date: TypedFact | None = None
    impugned_order_date: TypedFact | None = None
    appeal_filing_date: TypedFact | None = None
    certified_copy_applied: TypedFact | None = None
    amount_in_default_inr: TypedFact | None = None
    claim_amount_inr: TypedFact | None = None
    cirp_commencement_date: TypedFact | None = None
    liquidation_order_date: TypedFact | None = None
    acknowledgments: list[Acknowledgment] = Field(default_factory=list)
    other: dict[str, TypedFact] = Field(default_factory=dict, description="case-specific facts, snake_case keys")

    def all_facts(self) -> dict[str, TypedFact]:
        named = {k: v for k, v in self if isinstance(v, TypedFact)}
        return {**named, **self.other}


class RecordDocument(SrcRequired):
    id: str = Field(pattern=r"^D\d+$")
    kind: RecordDocKind
    date: dt.date | None = None
    gist: str = Field(max_length=400, description="What the document shows, neutrally")


class Issue(_Strict):
    id: str = Field(pattern=r"^I\d+$")
    text: str = Field(description="Neutral wording (CLAUDE.md §6.2)")
    provisions: list[str] = Field(default_factory=list)


class Ground(SrcRequired):
    id: str = Field(pattern=r"^[GR]\d+$")
    issue: str = Field(pattern=r"^I\d+$")
    heading: str = Field(max_length=240, description="One line; the full submission is sealed")


class AppealScope(_Strict):
    restricted_grounds: Literal["SEC61_3", "SEC61_4"] | None = None
    record_closed_after_turn: int = 3


class RecordConflict(_Strict):
    field: str
    note: str


class PublicUnspoiled(_Strict):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    case_uid: str = Field(pattern=r"^PC-[A-Z0-9-]+$")
    title_anon: str
    forum: Literal["NCLAT"] = "NCLAT"
    bench_city: str = Field(pattern=r"^[A-Z_]+$")
    law_as_of: dt.date = Field(description="decision date minus one day")
    proceeding_type: ProceedingType
    appellant_role: Role
    respondent_roles: list[Role] = Field(min_length=1)
    parties: list[Party] = Field(min_length=2)
    placeholders: list[Placeholder] = Field(default_factory=list)
    impugned_order: ImpugnedOrder
    chronology: list[Event] = Field(min_length=1)
    typed_facts: TypedFacts = Field(default_factory=TypedFacts)
    record_documents: list[RecordDocument] = Field(default_factory=list)
    issues: list[Issue] = Field(min_length=1)
    appellant_grounds: list[Ground] = Field(min_length=1)
    respondent_contentions: list[Ground] = Field(default_factory=list)
    statutes_in_play: list[str] = Field(default_factory=list, description="from the parties' submissions only")
    appeal_scope: AppealScope = Field(default_factory=AppealScope)
    record_conflicts: list[RecordConflict] = Field(default_factory=list)

    @model_validator(mode="after")
    def _references(self):
        def unique(ids, what):
            dup = {i for i in ids if ids.count(i) > 1}
            if dup:
                raise ValueError(f"duplicate {what} ids: {sorted(dup)}")
        events = [e.id for e in self.chronology]
        issues = [i.id for i in self.issues]
        unique(events, "event")
        unique(issues, "issue")
        unique([g.id for g in self.appellant_grounds + self.respondent_contentions], "ground")
        unique([p.token for p in self.parties] + [p.token for p in self.placeholders], "token")
        if any(not g.id.startswith("G") for g in self.appellant_grounds):
            raise ValueError("appellant ground ids start with G")
        if any(not g.id.startswith("R") for g in self.respondent_contentions):
            raise ValueError("respondent contention ids start with R")
        for g in self.appellant_grounds + self.respondent_contentions:
            if g.issue not in issues:
                raise ValueError(f"{g.id} points to unknown issue {g.issue}")
        facts = self.typed_facts.all_facts()
        for name, f in facts.items():
            if f.ref and f.ref not in events:
                raise ValueError(f"typed_facts.{name}.ref {f.ref} is not a chronology event")
        for a in self.typed_facts.acknowledgments:
            if a.ref and a.ref not in events:
                raise ValueError(f"acknowledgment ref {a.ref} is not a chronology event")
        for e in self.chronology:
            if e.conflict_ref and (e.conflict_ref not in facts or not facts[e.conflict_ref].conflict):
                raise ValueError(f"{e.id}.conflict_ref '{e.conflict_ref}' is not a conflicting typed fact")
        for c in self.record_conflicts:
            if c.field in facts and not facts[c.field].conflict:
                raise ValueError(f"record_conflicts lists '{c.field}' but the typed fact is not marked conflict")
        declared = {p.token for p in self.parties} | {p.token for p in self.placeholders}
        used = set(TOKEN_RE.findall(self.model_dump_json(exclude={"parties", "placeholders"})))
        if undeclared := used - declared:
            raise ValueError(f"tokens used but not declared in parties/placeholders: {sorted(undeclared)}")
        if not any(p.side == "APPELLANT" for p in self.parties) or not any(p.side == "RESPONDENT" for p in self.parties):
            raise ValueError("parties need at least one APPELLANT and one RESPONDENT")
        return self


# ---- ground truth (sealed) ----------------------------------------------------------------------------------

class AuthorityRef(_Strict):
    title: str
    citation: str | None = Field(None, description="only as printed in the judgment; never invented")
    authority_uid: str | None = None


class IssueFinding(SrcRequired):
    issue: str = Field(pattern=r"^I\d+$")
    finding: str = Field(pattern=r"^[A-Z0-9_]+$", description="short code, e.g. WITHIN_LIMITATION")
    holding: str | None = None
    provisions: list[str] = Field(default_factory=list)
    authorities_relied: list[AuthorityRef] = Field(default_factory=list)


class CitedAuthority(AuthorityRef):
    by: Literal["APPELLANT", "RESPONDENT"]


class Submissions(_Strict):
    appellant: str
    respondent: str | None = None


class BenchFraming(_Strict):
    issue_grouping: str | None = None
    interpretive_aids: list[str] = Field(default_factory=list)


class SubsequentHistory(_Strict):
    court: Literal["SC", "NCLAT_LARGER_BENCH", "OTHER"]
    date: dt.date
    result: str
    source: str | None = None


class PublicGroundTruth(_Strict):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    case_uid: str = Field(pattern=r"^PC-[A-Z0-9-]+$")
    decision_date: dt.date
    label: Label
    appellant_won: bool | None = Field(description="null = excluded from the binary metric (e.g. WITHDRAWN)")
    outcome_detail: str | None = None
    issue_findings: list[IssueFinding] = Field(min_length=1)
    ratio_decidendi: str
    operative_order_verbatim: str
    directions: list[str] = Field(default_factory=list)
    dissent: str | None = None
    submissions_full: Submissions
    authorities_cited_by_parties: list[CitedAuthority] = Field(default_factory=list)
    bench_framing: BenchFraming = Field(default_factory=BenchFraming)
    subsequent_history: list[SubsequentHistory] = Field(default_factory=list)

    @model_validator(mode="after")
    def _label_consistency(self):
        if self.label == "DISMISSED" and self.appellant_won is True:
            raise ValueError("DISMISSED with appellant_won=True")
        if self.label in ("ALLOWED", "PARTLY_ALLOWED") and self.appellant_won is False:
            raise ValueError(f"{self.label} with appellant_won=False")
        return self


# ---- manifest -----------------------------------------------------------------------------------------------

class RealParty(_Strict):
    token: Token
    name: str


class Real(_Strict):
    title: str
    appeal_numbers: list[str] = Field(min_length=1, description="one per connected appeal decided by this judgment")
    parties: list[RealParty] = Field(default_factory=list)
    bench_members: list[str] = Field(default_factory=list)
    other_identifiers: list[str] = Field(default_factory=list, description="CP/MA/IA numbers etc. removed from unspoiled")


class SourceDoc(_Strict):
    doc: DocName
    url: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pages: int = Field(ge=1)
    retrieved_at: dt.date | None = None


class Overlap(_Strict):
    reference_case_uids: list[str] = Field(default_factory=list)
    raw_precedent_ids: list[str] = Field(default_factory=list)


class Strata(_Strict):
    proceeding_type: ProceedingType
    appellant_role: Role
    year: int


class Build(_Strict):
    method: Literal["LLM_DRAFT+HUMAN_REVIEW", "MANUAL", "SYNTHETIC_TEMPLATE"]
    drafted_by: str | None = None
    reviewed_by: str | None = None
    reviewed_at: dt.date | None = None
    lawyer_checked: bool = False


class QA(_Strict):
    facts_verified: bool = False
    issues_neutral: bool = False
    issues_original: list[str] = Field(default_factory=list)
    leakage_scan_passed: bool = False
    anonymisation_checked: bool = False
    notes: str | None = None


class ProbeResult(_Strict):
    outcome_correct: bool | None = None
    identified_case: bool | None = None
    probed_at: dt.date | None = None


class PublicManifest(_Strict):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    case_uid: str = Field(pattern=r"^PC-[A-Z0-9-]+$")
    real: Real
    sources: list[SourceDoc] = Field(min_length=1)
    overlap_with_reference_db: Overlap = Field(default_factory=Overlap)
    in_scope: bool = Field(description="Phase 1: IBC appeals only")
    split: Split
    strata: Strata
    build: Build
    qa: QA = Field(default_factory=QA)
    contamination_probe: dict[str, ProbeResult] = Field(default_factory=dict)
