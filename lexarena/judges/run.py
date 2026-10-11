"""The bench (BUILD_PLAN Step 11; ARCHITECTURE §5; D-048, D-051, D-071).

For each persona and each presentation order: one judge call on the packet, the validator (judges/validate.py) and
THEMIS layer 1 on the law the opinion states, one revision with the exact problems if any, then fold and decide
(judges/bench.py). The judge model's role, temperature and seed come from config; every call goes through the LLM
client.

Inputs are resolved by the caller (the orchestrator, Step 9), which holds the full case: statute views as of the case
dates and under each alternative date reading (D-069), approved predicates, and the judge's `get_precedent` tool
(`tools_for(Role.JUDGE, ...)`), bound to the case's cut-off and exclusions. Nothing here can read the simulation date,
build data, ground truth or private turn data; the import-boundary test keeps it that way.

An LLM failure is raised, not turned into an abstention: abstention is a judicial outcome, a quota error is not.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Protocol

from lexarena import trace
from lexarena.agents.desk import KnowledgeDesk
from lexarena.judges.bench import decide_bench, fold_judge, require_supported
from lexarena.judges.packet import (
    COUNSEL,
    SIDE_ORDER,
    PrecedentFetcher,
    cited_precedent_uids,
    fetch_precedents,
    record_ids,
    render_audit_notes,
    render_case,
    render_issues,
    render_precedents,
    render_statutes,
    render_submissions,
    statutes_for_bench,
)
from lexarena.judges.personas import PersonaPrompt, PersonaRegistry
from lexarena.judges.validate import Allowed, check_opinion, finalize, normalize_ids
from lexarena.llm.client import LLMClient
from lexarena.memory.pinning import render as render_lessons
from lexarena.prompts import PromptStore, RenderedPrompt
from lexarena.schemas.bench import (
    ORDERS,
    PERSONAS,
    BenchVerdict,
    InvalidOpinion,
    JudgeDecision,
    JudgeOpinion,
    OpinionDraft,
    PresentationOrder,
)
from lexarena.schemas.case import AgentCaseView
from lexarena.schemas.config import AppConfig
from lexarena.schemas.lesson import Lesson
from lexarena.schemas.predicate import PredicateEntry
from lexarena.schemas.session import ThemisGlobalReport
from lexarena.schemas.transcript import PublishedTurn
from lexarena.storage.temporal import AsOf, StatuteView
from lexarena.themis_local.extract import extract_checklists
from lexarena.themis_local.layer1 import CaseFacts, alternative_readings, run_layer1
from lexarena.themis_local.verify import LawContext

ROLE = "judge"
log = logging.getLogger("lexarena.judges")
JSON_INDENT = 2  # literal-ok: readability of the previous answer shown in the revision prompt
NO_PROBLEMS = "(none: revise only where the answers to your lookups change your answer)"

# THEMIS layer 1 on a judge's stated law runs on its own role, sized for an opinion (D-092).
CHECK_ROLE = "judge_checker"


def single_orders(case_key: str, *, flip: bool = False) -> list[PresentationOrder]:
    """Single-order mode (D-093): one presentation order per persona, alternating across personas and flipping with a
    hash of the case, so over a run neither side is systematically read first."""
    start = (int.from_bytes(hashlib.sha256(case_key.encode("utf-8")).digest(), "big") + int(flip)) % len(ORDERS)
    return [ORDERS[(start + i) % len(ORDERS)] for i in range(len(PERSONAS))]


class StatuteSource(Protocol):
    def get_statute(self, statute_id: str, as_of: AsOf) -> StatuteView | None: ...

    def predicates(self, statute_id: str) -> list[PredicateEntry]: ...


BenchLaw = LawContext  # the bench decides on the same resolved law THEMIS checked (D-075)


def law_for_bench(
    case: AgentCaseView, turns: list[PublishedTurn], law: StatuteSource, as_of: AsOf, cfg: AppConfig
) -> BenchLaw:
    """Resolve every statute the bench may cite. `as_of` comes from the full case (`AsOf.for_case`), which only the
    orchestrator holds; the judges never see the dates it carries beyond the agent view's key dates."""
    ids = statutes_for_bench(case, turns)
    views = {sid: v for sid in ids if (v := law.get_statute(sid, as_of)) is not None}
    alternatives = [
        None if alt is None else {sid: v for sid in views if (v := law.get_statute(sid, alt)) is not None}
        for alt in alternative_readings(as_of, cfg.themis_local)
    ]
    return BenchLaw(views=views, alternatives=alternatives, predicates={sid: law.predicates(sid) for sid in views})


@dataclass(frozen=True)
class BenchInputs:
    case: AgentCaseView
    turns: list[PublishedTurn]
    law: BenchLaw
    fetch_precedent: PrecedentFetcher
    audit: ThemisGlobalReport | None = None  # shown as notes only if judging.show_audit_notes (D-078)
    lessons: list[Lesson] = field(default_factory=list)  # LEGAL_RULE lessons pinned for the bench (D-077)
    desk: KnowledgeDesk | None = None  # D-112: the bench's statute and own-lesson lookups; None turns them off


@dataclass
class BenchResult:
    decisions: list[JudgeDecision]
    verdict: BenchVerdict
    notes: list[str] = field(default_factory=list)


def _facts(case: AgentCaseView) -> CaseFacts:
    return CaseFacts(
        amounts={a.amount_id: a for a in case.record.amounts},
        key_dates={k.label: k.date for k in case.metadata.key_dates},
        date_fact_ids={k.label: k.fact_id for k in case.metadata.key_dates},
    )


def _stated_law(draft: OpinionDraft) -> str:
    parts = [f"{d.issue_id}: {d.finding} {d.application} {d.conclusion}" for d in draft.issue_decisions]
    return "\n".join([*parts, draft.overall_reasons])


class Bench:
    def __init__(
        self,
        llm: LLMClient,
        prompts: PromptStore,
        cfg: AppConfig,
        personas: PersonaRegistry,
        *,
        allow_unapproved_personas: bool = False,
        layer1: Callable[[OpinionDraft, BenchInputs, str], list[str]] | None = None,
    ) -> None:
        self._llm = llm
        self._prompts = prompts
        self._cfg = cfg
        self._personas = personas
        self._allow_unapproved = allow_unapproved_personas
        self._layer1 = layer1 or self._layer1_problems

    # ------------------------------------------------------------ checks

    def _layer1_problems(self, draft: OpinionDraft, inputs: BenchInputs, session_id: str) -> list[str]:
        """THEMIS layer 1 on the law the opinion states: a judge who misstates a threshold or period gets the same
        hard error counsel would (ARCHITECTURE §5). Warnings are not problems (non-negotiable 7)."""
        if not self._cfg.judging.check_reasons_with_layer1:
            return []
        law = inputs.law
        cited = {rid for d in draft.issue_decisions for rid in d.governing_rule_ids if rid in law.views}
        if not cited:
            return []
        views = {sid: law.views[sid] for sid in sorted(cited)}
        predicates = {sid: law.predicates.get(sid, []) for sid in views}
        facts = _facts(inputs.case)
        report = extract_checklists(
            self._llm,
            self._prompts,
            self._cfg,
            _stated_law(draft),
            views,
            predicates,
            facts.amounts,
            session_id=session_id,
            role=CHECK_ROLE,
        )
        alternatives = (
            None
            if law.alternatives is None
            else [None if alt is None else {s: alt[s] for s in views if s in alt} for alt in law.alternatives]
        )
        result = run_layer1(
            report.checklists, views, predicates, facts, self._cfg.themis_local, alternatives=alternatives
        )
        return [f"LAYER1 {e.code} on {e.statute_id}: {e.detail}" for e in result.hard_errors]

    def _problems(self, draft: OpinionDraft, allowed: Allowed, inputs: BenchInputs, session_id: str) -> list[str]:
        return check_opinion(draft, allowed) + self._layer1(draft, inputs, session_id)

    # ------------------------------------------------------------ calls

    def _ask(self, prompt: RenderedPrompt, allowed: Allowed, session_id: str) -> OpinionDraft:
        draft = self._llm.complete_json(role=ROLE, user=prompt, schema=OpinionDraft, session_id=session_id).value
        draft, changed = normalize_ids(draft, allowed)
        if changed:
            log.info("session %s: %d malformed IDs repaired in a judge's answer (D-101)", session_id, changed)
        return draft

    def _opinion(
        self,
        persona: PersonaPrompt,
        order: PresentationOrder,
        shared: dict[str, str],
        inputs: BenchInputs,
        allowed: Allowed,
        session_id: str,
    ) -> JudgeOpinion | InvalidOpinion:
        refs = self._cfg.prompts
        first, second = SIDE_ORDER[order]
        original = self._prompts.render(
            refs.judge_decide.id,
            refs.judge_decide.version,
            persona=persona.rendered.text,
            max_lookups=str(self._cfg.judging.lookups_per_opinion),
            first_side=COUNSEL[first],
            second_side=COUNSEL[second],
            submissions=render_submissions(inputs.case, inputs.turns, order),
            audit_notes=render_audit_notes(
                inputs.audit if self._cfg.judging.show_audit_notes else None,
                order,
                contradictions=self._cfg.judging.show_audit_contradictions,
            ),
            **shared,
        )
        draft = self._ask(original, allowed, session_id)
        # D-112: the judge's lookups are answered in its one revision round; a provision it found becomes citable and
        # is checked like any other, for this opinion only.
        cap = self._cfg.judging.lookups_per_opinion
        answers = None
        if inputs.desk is not None and cap and draft.lookups:
            got = inputs.desk.serve(list(draft.lookups[:cap]))
            answers = got.text
            if got.statutes:
                allowed = replace(allowed, statute_ids=allowed.statute_ids | set(got.statutes))
                inputs = replace(
                    inputs,
                    law=LawContext(
                        views={**inputs.law.views, **got.statutes},
                        alternatives=inputs.law.alternatives,
                        # the desk's resolver filled in the predicates of what it found (orchestrator, D-112)
                        predicates={s: inputs.law.predicates.get(s, []) for s in {*inputs.law.views, *got.statutes}},
                    ),
                )
            trace.event("judge_lookups", asked=[x.model_dump() for x in draft.lookups[:cap]], answers=answers)
        problems = self._problems(draft, allowed, inputs, session_id)
        if not problems and answers is None:
            return finalize(draft, order, revised=False, problems=[])
        revision = self._prompts.render(
            refs.judge_revise.id,
            refs.judge_revise.version,
            original=original.text,
            previous=draft.model_dump_json(indent=JSON_INDENT),
            problems="\n".join(f"- {p}" for p in problems) or NO_PROBLEMS,
            lookups=answers or "(none)",
            rule_ids=", ".join(sorted(allowed.statute_ids | allowed.precedent_uids)),
            record_ids=", ".join(sorted(allowed.record_ids)),
        )
        revised = self._ask(revision, allowed, session_id)
        return finalize(revised, order, revised=True, problems=self._problems(revised, allowed, inputs, session_id))

    # ------------------------------------------------------------ the bench

    def decide(self, inputs: BenchInputs, *, session_id: str) -> BenchResult:
        require_supported(self._cfg.judging)
        # Every persona is checked before the first call, so an unapproved prompt never spends quota.
        personas = [self._personas.prompt(p, allow_unapproved=self._allow_unapproved) for p in PERSONAS]
        case = inputs.case
        issue_ids = [i.issue_id for i in case.framed_issues]
        precedents = fetch_precedents(cited_precedent_uids(inputs.turns), inputs.fetch_precedent)
        allowed = Allowed(
            issue_ids=issue_ids,
            statute_ids=set(inputs.law.views),
            precedent_uids=set(precedents),
            record_ids=record_ids(case),
        )
        shared = {
            "case": render_case(case),
            "issues": render_issues(case),
            "issue_ids": ", ".join(issue_ids),
            "statutes": render_statutes(inputs.law.views),
            "precedents": render_precedents(precedents),
            "lessons": render_lessons(inputs.lessons),
        }
        notes = [
            f"precedent {uid} cited by counsel is not available to the bench"
            for uid in cited_precedent_uids(inputs.turns)
            if uid not in precedents
        ]
        notes += [
            f"persona {p.persona} ran on an UNAPPROVED prompt ({p.rendered.prompt_id})"
            for p in personas
            if not p.approved
        ]
        decisions = []
        one = single_orders(case.case_id) if self._cfg.judging.orders_per_persona < len(ORDERS) else None
        for n, persona in enumerate(personas):
            orders = ORDERS if one is None else (one[n],)
            opinions = {}
            for o in orders:
                with trace.tags(phase="BENCH", persona=persona.persona, order=o):
                    opinions[o] = self._opinion(persona, o, shared, inputs, allowed, session_id)
                    trace.event("opinion", opinion=opinions[o].model_dump(mode="json"))
            decisions.append(
                fold_judge(
                    persona.persona,
                    opinions,
                    issue_ids,
                    self._cfg.judging,
                    persona_prompt=persona.rendered.prompt_id,
                    persona_sha256=persona.rendered.sha256,
                    persona_approved=persona.approved,
                )
            )
        return BenchResult(
            decisions=decisions, verdict=decide_bench(decisions, issue_ids, self._cfg.judging), notes=notes
        )
