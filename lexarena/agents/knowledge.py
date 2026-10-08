"""A lawyer's knowledge base: three parts, each with its own rules (ARCHITECTURE §2, §4; SPEC B, C, E6, F; D-079).

1. Regulation memory: the Law DB with its approved `temporal_overlay` rows and predicates, as the provisions stood
   on the case dates (`LawContext`, resolved once by the orchestrator). Read-only. Identical for both sides. A section
   not in force on the case dates is absent, and a value that changes over time is shown as dated, never as today's.
2. Case library: the precedent DB, only through the case-scoped retrieval tools: decided before the case, its own
   overlapping precedents excluded, both applied by the store (SPEC B1, B2; D-052). Lawyers search by meaning and fetch
   by `precedent_uid`; the same `top_k`, card size and query count for both sides. A precedent is cited by the uid a
   tool returned; nothing else is citable.
3. Experience base: lessons from earlier cases, keyed by the party status the side represents (never by agent, SPEC
   F6) and the case's statutes, pinned at the start within the same count and token budget for both sides (E6).
   Read-only during the session; written only by reflection after the verdict, and only in LEARN runs.

Nothing in any part comes from the real judgment of this case or from the other side's private data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lexarena.judges.packet import render_statutes
from lexarena.memory.pinning import render as render_lessons
from lexarena.retrieval.tools import RetrievalTools, tools_for
from lexarena.schemas.agent import ResearchQuery
from lexarena.schemas.lesson import Lesson
from lexarena.schemas.retrieval import PrecedentCard
from lexarena.storage.policy import Role
from lexarena.themis_local.verify import LawContext

ToolFn = Callable[..., Any]


@dataclass(frozen=True)
class RegulationMemory:
    law: LawContext

    def statute_ids(self) -> set[str]:
        return set(self.law.views)

    def render(self) -> str:
        return render_statutes(self.law.views)


@dataclass(frozen=True)
class CaseLibrary:
    """The tools one role may use; built with `tools_for`, so a role without search has no search here."""

    tools: dict[str, ToolFn]

    @classmethod
    def for_role(cls, role: Role, tools: RetrievalTools) -> CaseLibrary:
        return cls(tools_for(role, tools))

    @property
    def can_search(self) -> bool:
        return "find_authority" in self.tools

    def research(self, queries: list[ResearchQuery], max_queries: int) -> list[PrecedentCard]:
        """Run at most `max_queries` searches; every card comes from the case-scoped store, unique by uid."""
        if not self.can_search:
            raise PermissionError("this role may not search the case library")
        cards: dict[str, PrecedentCard] = {}
        for q in queries[:max_queries]:
            tool = self.tools["find_authority" if q.kind == "authority" else "find_similar_cases"]
            result = tool(q.query, q.statutes or None)
            for card in result.hits:
                cards.setdefault(card.precedent_uid, card)
        return list(cards.values())

    def fetch(self, precedent_uid: str, part: str = "ratio") -> Any:
        return self.tools["get_precedent"](precedent_uid, part)


@dataclass(frozen=True)
class ExperienceBase:
    lessons: list[Lesson] = field(default_factory=list)

    def ids(self) -> list[str]:
        return [x.lesson_id for x in self.lessons]

    def render(self) -> str:
        return render_lessons(self.lessons)


@dataclass(frozen=True)
class LawyerKnowledge:
    regulation: RegulationMemory
    library: CaseLibrary
    experience: ExperienceBase


def render_cards(cards: list[PrecedentCard]) -> str:
    if not cards:
        return "(none)"
    return "\n".join(
        f"[{c.precedent_uid}] {c.case_title} ({c.forum}, {c.decision_date}): {c.rule}"
        + (f" | matched: {c.matched}" if c.matched else "")
        for c in cards
    )
