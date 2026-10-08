"""What the advocate model returns (BUILD_PLAN Step 9; SPEC H3, A2, E6; D-053, D-075).

A draft is the argument's text plus the claims it rests on, each naming the record items, statute and precedents it
relies on. THEMIS verifies the claims and the text (layers 1 and 2); the published turn keeps both (`PublicClaim`).
A claim may cite nothing (D-053: citing is never required); a citation that is wrong is what THEMIS catches.
Plain strings and lists only, so strict JSON-schema modes accept it.
"""

from __future__ import annotations

from typing import Literal

from lexarena.schemas.base import StoredModel


class DraftClaim(StoredModel):
    type: Literal["FACT", "LAW"]
    text: str
    record_ids: list[str]
    statute_id: str | None
    precedent_ids: list[str]  # precedent_uid values, as the search cards give them (D-052)


class LawyerDraft(StoredModel):
    text: str
    issues_addressed: list[str]
    claims: list[DraftClaim]


class ResearchQuery(StoredModel):
    kind: Literal["facts", "authority"]
    query: str
    statutes: list[str]


class ResearchPlan(StoredModel):
    """First half of the private strategy phase: what to look up (D-053)."""

    queries: list[ResearchQuery]


class StrategyNotes(StoredModel):
    """Second half: the side's plan, kept in its own session memory, never shown to the opponent or judges."""

    issues_to_press: list[str]
    expected_attacks: list[str]
    authorities_held: list[str]  # precedent_uid values found in research, held for use
    plan: str
