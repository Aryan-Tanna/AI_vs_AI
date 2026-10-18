"""A side's knowledge desk: answers the lookups an agent asks for in its submission (D-112).

The agent decides what it wants from each part of its own knowledge base:
- STATUTE: a provision of the Law DB as it stood on this case's dates (resolved server-side; the agent never sees a
  date it was not given). Once found it joins that side's regulation memory, so it may be cited and THEMIS checks it.
- AUTHORITY_SEARCH, SIMILAR_CASES: a search of the case library (same date cut-off and exclusions as every search);
  the cards found join the authorities the side holds.
- PRECEDENT: the rule of one precedent by its ID, if it is within the case's scope.
- LESSONS: the side's own experience base, ranked by meaning against the query, from the lessons its party status may
  use under this case's law (never the other side's memory, never the judges').

Lookups are deferred, not tool calls: they ride on the submission and are answered before the side's next one, so they
cost no model call. Both sides get the same number of lookups and the same answer budget (`session.lookups_per_turn`,
`session.lookup_tokens`); what one side looked up is never shown to the other.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from lexarena.agents.knowledge import CaseLibrary, render_cards
from lexarena.judges.packet import render_statutes
from lexarena.memory.pinning import lesson_line
from lexarena.schemas.agent import KnowledgeLookup, ResearchQuery
from lexarena.schemas.bench import JudgeLookup
from lexarena.schemas.config import AppConfig
from lexarena.schemas.lesson import Lesson
from lexarena.schemas.retrieval import PrecedentCard
from lexarena.storage.temporal import StatuteView

StatuteResolver = Callable[[str], StatuteView | None]
LessonSearch = Callable[[str, int], list[Lesson]]
NO_LOOKUPS = "(none: list lookups in your submission to have them answered here before your next one)"
OMITTED = "[omitted: the answers to your lookups reached their budget]"


@dataclass
class DeskAnswer:
    text: str
    statutes: dict[str, StatuteView] = field(default_factory=dict)
    cards: list[PrecedentCard] = field(default_factory=list)


class KnowledgeDesk:
    def __init__(
        self, *, statute: StatuteResolver, library: CaseLibrary, lessons: LessonSearch, cfg: AppConfig
    ) -> None:
        self._statute = statute
        self._library = library
        self._lessons = lessons
        self._cfg = cfg

    def _one(
        self,
        lookup: KnowledgeLookup | JudgeLookup,
        out: DeskAnswer,
        held_statutes: set[str],
        held_precedents: set[str],
    ) -> str:
        q = lookup.query.strip()
        head = f"LOOKUP {lookup.kind} '{q}':"
        if not q:
            return f"{head} empty query"
        if lookup.kind == "STATUTE":
            view = self._statute(q)
            if view is None:
                return f"{head} no provision in the Law DB matches it, or it was not in force on this case's dates"
            if view.statute_id in held_statutes:  # D-135: say so, rather than serve the same text again
                return (  # D-145: lawyers re-asked for sub-section text the Law DB does not hold (DEV_0010, DEV_0011)
                    f"{head} [{view.statute_id}] is already in your regulation memory, as shown above; nothing new: "
                    "the Law DB holds no fuller text of it, so asking again cannot return more"
                )
            out.statutes[view.statute_id] = view
            return f"{head} now in your regulation memory\n{render_statutes({view.statute_id: view})}"
        if lookup.kind in ("AUTHORITY_SEARCH", "SIMILAR_CASES"):
            kind = "authority" if lookup.kind == "AUTHORITY_SEARCH" else "facts"
            hits = self._library.research([ResearchQuery(kind=kind, query=q, statutes=[])], 1)
            cards = [c for c in hits if c.precedent_uid not in held_precedents]  # D-135: only what is new to this side
            out.cards += cards
            already = len(hits) - len(cards)
            if not cards:
                return f"{head} nothing new: the {already} authorities found are already among yours"
            more = f" ({already} more found that you already hold)" if already else ""
            return f"{head} {len(cards)} new found{more}, now among the authorities you hold\n{render_cards(cards)}"
        if lookup.kind == "PRECEDENT":
            got = self._library.fetch(q, "ratio")
            if got is None:
                return f"{head} no precedent with that ID is available for this case"
            return f"{head} [{got.precedent_uid}] {got.case_title} ({got.decision_date}): {got.text}"
        found = self._lessons(q, self._cfg.session.lookup_lessons_k)
        lines = "\n".join(lesson_line(x) for x in found) or "(no lesson in your experience base matches)"
        return f"{head}\n{lines}"

    def serve(
        self,
        lookups: Sequence[KnowledgeLookup | JudgeLookup],
        *,
        held_statutes: set[str] | None = None,
        held_precedents: set[str] | None = None,
    ) -> DeskAnswer:
        """`held_*`: what the asking side already has (D-135); a lookup for it is answered as nothing new."""
        s = self._cfg.session
        out = DeskAnswer(text="")
        budget = s.lookup_tokens * self._cfg.llm.chars_per_token
        parts: list[str] = []
        used = 0
        for lookup in lookups[: s.lookups_per_turn]:
            text = self._one(lookup, out, held_statutes or set(), held_precedents or set())
            if used + len(text) > budget:
                room = int(budget - used)
                parts.append(text[:room] + "\n" + OMITTED if room > 0 else OMITTED)
                break
            parts.append(text)
            used += len(text)
        dropped = len(lookups) - s.lookups_per_turn
        if dropped > 0:
            parts.append(f"[{dropped} lookup(s) beyond the limit of {s.lookups_per_turn} were not answered]")
        out.text = "\n\n".join(parts) or NO_LOOKUPS
        return out
