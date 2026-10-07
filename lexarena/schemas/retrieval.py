"""Objects exchanged by the retrieval tools (BUILD_PLAN Step 5, SPEC B1, B2, B7).

`CaseScope` is fixed by the orchestrator from the full case and bound into the repository and the tools; no tool
argument can change it, so an agent cannot widen its own search (D-052).

`PrecedentView` is what an agent sees of a whole precedent (`get_precedent(..., part="all")`): an allow-list of
the record's fields plus `precedent_uid`, the unique ID agents cite (precedent_id values collide across different
cases, D-024). `is_overruled` is left out: it states the status today, which would leak a later overruling into
an earlier case (SPEC B8, D-052). Searches return compact `PrecedentCard`s instead (D-055).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import Field

from lexarena.schemas.base import NonEmptyStr, StoredModel
from lexarena.schemas.case import Amount, Case, ContestedFact, Exhibit, StipulatedFact

AGENT_PRECEDENT_FIELDS = (
    "precedent_uid",
    "precedent_id",
    "case_title",
    "appeal_number",
    "forum",
    "bench",
    "decision_date",
    "final_order",
    "statutes_cited",
    "statutes_normalized",
    "material_facts",
    "legal_issues",
    "ratio_decidendi",
    "operative_order",
    "summary",
)


class CaseScope(StoredModel):
    """What one case may see of the precedent DB: decided strictly before `decided_before`, not excluded."""

    decided_before: date
    excluded_precedent_ids: list[NonEmptyStr]

    @classmethod
    def from_case(cls, case: Case) -> CaseScope:
        return cls(
            decided_before=case.agent_view.metadata.simulation_date,
            excluded_precedent_ids=list(case.build.excluded_precedent_ids),
        )


class PrecedentView(StoredModel):
    precedent_uid: NonEmptyStr
    precedent_id: NonEmptyStr
    case_title: str
    appeal_number: str
    forum: str
    bench: str
    decision_date: str
    final_order: str
    statutes_cited: list[str]
    statutes_normalized: list[str]
    material_facts: str
    legal_issues: str
    ratio_decidendi: str
    operative_order: str
    summary: str
    score: float | None = Field(default=None, description="similarity; None when fetched by ID")

    @classmethod
    def from_payload(cls, payload: dict[str, Any], score: float | None = None) -> PrecedentView:
        return cls(**{k: payload[k] for k in AGENT_PRECEDENT_FIELDS}, score=score)


PrecedentPart = Literal["ratio", "facts", "issues", "order", "summary", "all"]


class PrecedentCard(StoredModel):
    """One search hit, compact (D-055): who, when, which statutes, the precedent's rule and the passage that
    matched the query, each capped at `retrieval.card_text_tokens`. The full text is fetched by ID, part by part."""

    precedent_uid: NonEmptyStr
    precedent_id: NonEmptyStr
    case_title: str
    forum: str
    decision_date: str
    final_order: str
    statutes: list[str] = Field(description="Law DB IDs the precedent cites (statutes_normalized)")
    rule: str = Field(description="ratio part 1, the abstract legal rule")
    matched: str = Field(description="the passage that best matched the query")
    score: float
    score_kind: Literal["RERANKER", "VECTOR"]


class PrecedentExcerpt(StoredModel):
    """One part of a precedent, fetched by ID (D-055)."""

    precedent_uid: NonEmptyStr
    precedent_id: NonEmptyStr
    case_title: str
    decision_date: str
    part: PrecedentPart
    text: str


class SearchResult(StoredModel):
    hits: list[PrecedentCard]
    statute_filter: list[str] = Field(description="Law DB IDs the search was restricted to (empty: no filter)")
    ignored_statutes: list[str] = Field(description="statutes given by the caller that match no Law DB ID")


RecordItem = StipulatedFact | ContestedFact | Exhibit | Amount


class RecordItemResult(StoredModel):
    kind: Literal["STIPULATED_FACT", "CONTESTED_FACT", "EXHIBIT", "AMOUNT"]
    item: RecordItem
