"""The ClaimSet: what Haiku extracts from a turn, and what Stage A checks (CLAUDE.md §8.3)."""
import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")

ComputationRule = Literal["ART137_LIMITATION", "SEC61_APPEAL", "SEC62_APPEAL", "SEC9_NOTICE", "SEC10A_BAR", "SEC4_THRESHOLD"]


class Computation(_Out):
    """A calculation the advocate asserts, with the inputs it used, so Stage A can redo it."""
    rule: ComputationRule
    default_date: dt.date | None = None
    acknowledgment_dates: list[dt.date] = Field(default_factory=list)
    filing_date: dt.date | None = None
    order_date: dt.date | None = None
    delivery_date: dt.date | None = None
    amount_inr: float | None = None
    asserted_outcome: Literal["WITHIN", "BARRED", "MET", "NOT_MET", "PREMATURE", "IN_TIME", "CONDONABLE", "BEYOND_LIMIT"] | None = None
    asserted_date: dt.date | None = Field(None, description="e.g. the expiry date the advocate states")


class Claim(_Out):
    id: str = Field(pattern=r"^C\d+$")
    kind: Literal["DATE", "AMOUNT", "DAY_COUNT", "COMPUTATION", "PROVISION", "AUTHORITY", "RECORD_FACT"]
    text: str = Field(description="The claim as asserted in the turn")
    fact_key: str | None = Field(None, description="typed_facts key this claim states, e.g. date_of_default")
    record_ref: str | None = Field(None, description="chronology event (E3) or record document (D2) relied on")
    date: dt.date | None = None
    amount_inr: float | None = None
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    days: int | None = None
    computation: Computation | None = None
    provision: str | None = Field(None, description="as cited, e.g. 'Section 18 of the Limitation Act'")
    authority_title: str | None = None
    authority_court: Literal["SC", "NCLAT", "HC", "NCLT", "OTHER"] | None = None
    proposition: str | None = Field(None, description="what the advocate says the authority held")
    declared_by_advocate: bool = True


class ClaimSet(_Out):
    claims: list[Claim]


class StageBFinding(_Out):
    code: Literal["ERR_MISATTRIBUTED_RATIO", "ERR_UNSUPPORTED_BY_RECORD", "ERR_NEW_FACT"]
    claim_id: str
    evidence: str = Field(description="Short quote or reason")


class StageBOutput(_Out):
    findings: list[StageBFinding]
