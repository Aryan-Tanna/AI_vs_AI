"""The advocate agents LEX-P and LEX-D (BUILD_PLAN Step 9; SPEC E6, I2; D-053, D-055, D-079).

Both sides are this class with the same model, settings and templates. What differs by side is listed in
`Assembled.side_specific` and nothing else: the role line, the side's pinned lessons (same budget), its own private plan
and the authorities its own research found (same query count).

Every call is assembled in one fixed order, shared prefix first (rules, case, issues, regulation memory), so provider
prompt caching applies. The input budget is `session.lawyer_input_tokens`: when the hearing so far does not fit, the
oldest turns are condensed into their claims ledger first, then dropped oldest first (D-055); the same rule for both
sides. No step summarises with a model.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from lexarena.agents.desk import NO_LOOKUPS, KnowledgeDesk
from lexarena.agents.knowledge import LawyerKnowledge, render_cards
from lexarena.judges.packet import COUNSEL, render_case, render_issues, render_statutes
from lexarena.llm.client import LLMClient
from lexarena.prompts import PromptStore, RenderedPrompt
from lexarena.schemas.agent import LawyerDraft, ResearchPlan, StrategyNotes
from lexarena.schemas.base import Side
from lexarena.schemas.case import AgentCaseView
from lexarena.schemas.config import AppConfig
from lexarena.schemas.retrieval import PrecedentCard
from lexarena.schemas.transcript import PublishedTurn

ROLE = "lawyer"
CONDENSED = "[earlier turns condensed to their claims]"
DROPPED = "[earliest turns omitted to fit the budget]"
FOUND_HEADING = "PROVISIONS YOU LOOKED UP (citable like the regulation memory)"


@dataclass(frozen=True)
class Assembled:
    """The sections of one lawyer call, by name, so the two sides' inputs can be compared (Step 9 acceptance)."""

    shared: dict[str, str]
    side_specific: dict[str, str]
    prompt: RenderedPrompt


def _full(turn: PublishedTurn) -> str:
    flags = "".join(f"\n    VERIFIER FLAG {f.code}" for f in turn.visible_flags)
    return f"Turn {turn.turn} ({turn.turn_type}) {COUNSEL[turn.speaker]}:\n{turn.published_text}{flags}"


def _ledger(turn: PublishedTurn) -> str:
    claims = "; ".join(c.text for c in turn.claims) or "(no claims listed)"
    return f"Turn {turn.turn} ({turn.turn_type}) {COUNSEL[turn.speaker]}, claims: {claims}"


TURN_INSTRUCTION = {  # D-135: only the current turn type's instruction is shown, so no part labels leak into speech
    "OPENING": "agent_turn_opening",
    "REBUTTAL": "agent_turn_rebuttal",
    "CLOSING": "agent_turn_closing",
}


def condense(turns: list[PublishedTurn], fits: Callable[[str], bool]) -> str:
    """The longest faithful rendering that fits: full turns, then oldest-first ledgers, then oldest-first drops."""
    if not turns:
        return "(the hearing has not started)"
    for n_ledger in range(len(turns) + 1):
        lines = ([CONDENSED] if n_ledger else []) + [_ledger(t) for t in turns[:n_ledger]]
        lines += [_full(t) for t in turns[n_ledger:]]
        text = "\n\n".join(lines)
        if fits(text):
            return text
    for n_drop in range(1, len(turns) + 1):
        text = "\n\n".join([DROPPED, *(_ledger(t) for t in turns[n_drop:])])
        if fits(text):
            return text
    return DROPPED


class Lawyer:
    def __init__(
        self,
        side: Side,
        case: AgentCaseView,
        knowledge: LawyerKnowledge,
        llm: LLMClient,
        prompts: PromptStore,
        cfg: AppConfig,
        *,
        session_id: str,
        exhibit_contents: bool = True,
        desk: KnowledgeDesk | None = None,
        hearing_year: int | None = None,
    ) -> None:
        self.side = side
        self._case = case
        self.knowledge = knowledge
        self._llm = llm
        self._prompts = prompts
        self._cfg = cfg
        self._session_id = session_id
        self._exhibits = exhibit_contents
        self._hearing_year = hearing_year  # D-144: the year only; the full decision date stays server-side
        self.notes: StrategyNotes | None = None
        self.held: list[PrecedentCard] = []
        # D-135: this side's own verifier's repetition warning on its last published turn (its private data, never
        # the opponent's); shown with its next submission only.
        self.repetition_note: str | None = None
        self._desk = desk
        # D-112: the provisions both sides start with stay shared; what this side looked up is side-specific.
        self._base_statutes = set(knowledge.regulation.law.views)
        self.lookup_answers = NO_LOOKUPS  # D-112: answers to the lookups of this side's last published submission

    # ------------------------------------------------------------ assembly

    def _render(self, name: str, **values: str) -> RenderedPrompt:
        ref = getattr(self._cfg.prompts, name)
        return self._prompts.render(ref.id, ref.version, **values)

    def _shared(self) -> dict[str, str]:
        return {
            "rules": self._render("agent_rules", hearing_era=self._era()).text,
            "case": render_case(self._case, exhibit_contents=self._exhibits),
            "issues": render_issues(self._case),
            "statutes": render_statutes(
                {k: v for k, v in self.knowledge.regulation.law.views.items() if k in self._base_statutes}
            ),
        }

    def _era(self) -> str:
        if self._hearing_year is None:
            return ""
        return self._render("hearing_era", year=str(self._hearing_year)).text.strip()

    def _role(self) -> str:
        parties = [p for p in self._case.parties if p.simulation_side == self.side]
        return self._render(
            "agent_role",
            side_label=COUNSEL[self.side].replace("'s counsel", ""),
            parties="; ".join(f"{p.pseudonym} ({p.status})" for p in parties),
            reliefs="; ".join(getattr(self._case.reliefs_sought, self.side)) or "(none stated)",
        ).text

    def _tokens(self, text: str) -> float:
        return len(text) / self._cfg.llm.chars_per_token

    def assemble_turn(
        self, turn: int, turn_type: str, transcript: list[PublishedTurn], feedback: str | None
    ) -> Assembled:
        shared = self._shared()
        side = {
            "role": self._role(),
            "lessons": self.knowledge.experience.render(),
            "plan": self.notes.model_dump_json() if self.notes else "(no plan)",
            "authorities": render_cards(self.held),
            "lookups": self._lookups_section(),
        }
        s = self._cfg.session
        fixed = {
            **shared,
            **side,
            "turn": str(turn),
            "turn_type": turn_type,
            "turn_instruction": self._render(TURN_INSTRUCTION[turn_type]).text.strip(),
            "verifier_note": self._render("agent_repetition_note", detail=self.repetition_note).text.strip() + "\n"
            if self.repetition_note
            else "",
            "max_words": str(int(s.max_turn_tokens * s.words_per_token)),
            "max_lookups": str(s.lookups_per_turn),
            "feedback": f"\nThe verifier rejected your previous draft. Fix exactly these problems:\n{feedback}\n"
            if feedback
            else "",
        }
        base = self._render("agent_turn", transcript="", **fixed).text
        room = s.lawyer_input_tokens - self._tokens(base)
        hearing = condense(transcript, lambda text: self._tokens(text) <= room)
        shared_with_hearing = {**shared, "transcript": hearing}
        return Assembled(shared_with_hearing, side, self._render("agent_turn", transcript=hearing, **fixed))

    # ------------------------------------------------------------ calls

    def prepare(self) -> StrategyNotes:
        """The private strategy phase (D-053): plan research, run it in the case library, then plan the case."""
        shared, role, lessons = self._shared(), self._role(), self.knowledge.experience.render()
        max_q = self._cfg.session.research_queries
        plan_prompt = self._render("agent_plan", role=role, lessons=lessons, max_queries=str(max_q), **shared)
        plan = self._llm.complete_json(role=ROLE, user=plan_prompt, schema=ResearchPlan, session_id=self._session_id)
        cards = self.knowledge.library.research(plan.value.queries, max_q)
        notes_prompt = self._render("agent_notes", role=role, lessons=lessons, research=render_cards(cards), **shared)
        notes = self._llm.complete_json(
            role=ROLE, user=notes_prompt, schema=StrategyNotes, session_id=self._session_id
        ).value
        found = {c.precedent_uid: c for c in cards}
        held = [uid for uid in dict.fromkeys(notes.authorities_held) if uid in found]  # only what research returned
        self.notes = notes.model_copy(update={"authorities_held": held})
        self.held = [found[uid] for uid in held]
        return self.notes

    def _lookups_section(self) -> str:
        found = {k: v for k, v in self.knowledge.regulation.law.views.items() if k not in self._base_statutes}
        if not found:
            return self.lookup_answers
        return f"{self.lookup_answers}\n\n{FOUND_HEADING}\n{render_statutes(found)}"

    def answer_lookups(self, draft: LawyerDraft) -> str:
        """Serve the lookups of this side's published submission (D-112): statutes found join its regulation memory,
        precedents found join the authorities it holds, and the answers are shown with its next submission."""
        if self._desk is None:
            return self.lookup_answers
        answer = self._desk.serve(
            draft.lookups,
            held_statutes=set(self.knowledge.regulation.law.views),
            held_precedents={c.precedent_uid for c in self.held},
        )
        self.knowledge.regulation.law.views.update(answer.statutes)
        for card in answer.cards:
            if all(c.precedent_uid != card.precedent_uid for c in self.held):
                self.held.append(card)
        self.lookup_answers = answer.text
        return answer.text

    def draft(
        self, turn: int, turn_type: str, transcript: list[PublishedTurn], feedback: str | None
    ) -> tuple[LawyerDraft, Assembled]:
        assembled = self.assemble_turn(turn, turn_type, transcript, feedback)
        out = self._llm.complete_json(role=ROLE, user=assembled.prompt, schema=LawyerDraft, session_id=self._session_id)
        return out.value, assembled
