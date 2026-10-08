"""One THEMIS-LOCAL check of one draft: layer 1 and layer 2 together (BUILD_PLAN Step 8; ARCHITECTURE §4; D-075).

`LawContext` is the law a session works with, resolved once by the orchestrator from the full case: statute views on
the case dates, the same views under each alternative date reading (D-069), and the approved predicates. The bench
uses the same object (judges/run.py), so lawyers, THEMIS and judges argue, check and decide on identical law.

Both THEMIS-LOCAL instances are this class with the same config (SPEC I2: identical rules); each gets only its own
side's earlier turns for the repetition check.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lexarena.embedding import Embedder
from lexarena.llm.client import LLMClient
from lexarena.prompts import PromptStore
from lexarena.schemas.agent import DraftClaim, LawyerDraft
from lexarena.schemas.case import AgentCaseView
from lexarena.schemas.config import AppConfig
from lexarena.schemas.predicate import PredicateEntry
from lexarena.schemas.transcript import ClaimAssessment, ExtractedChecklist, ThemisWarning
from lexarena.storage.temporal import StatuteView
from lexarena.themis_local.extract import extract_checklists
from lexarena.themis_local.layer1 import CaseFacts, run_layer1
from lexarena.themis_local.layer2 import (
    Layer2Result,
    PrecedentFetcher,
    Problem,
    check_citations,
    check_claim_references,
    check_repetition,
    record_index,
    review_fidelity,
)


@dataclass(frozen=True)
class LawContext:
    views: dict[str, StatuteView]
    # `views` re-resolved under each alternative date reading (None where the case lacks that date). None means not
    # resolved: layer 1 then never checks a threshold (D-069).
    alternatives: list[dict[str, StatuteView] | None] | None
    predicates: dict[str, list[PredicateEntry]]


@dataclass(frozen=True)
class VerifyContext:
    case: AgentCaseView
    law: LawContext
    fetch_precedent: PrecedentFetcher
    turn: int
    opponent_last: str | None  # the opponent's latest published text, for responsiveness
    own_earlier: list[str]  # this side's earlier published texts, for repetition


@dataclass
class Verification:
    claims: list[tuple[str, DraftClaim]]
    hard_errors: list[Problem] = field(default_factory=list)
    warnings: list[ThemisWarning] = field(default_factory=list)
    assessments: list[ClaimAssessment] = field(default_factory=list)
    checklists: list[ExtractedChecklist] = field(default_factory=list)
    rule_coverage: float = 1.0  # SPEC D6 S_rule: share of applicable checklist items the argument addresses
    responsiveness: float | None = None


def claim_ids(draft: LawyerDraft, turn: int) -> list[tuple[str, DraftClaim]]:
    return [(f"T{turn:02d}-C{n}", c) for n, c in enumerate(draft.claims, 1)]  # SPEC H3 claim ID shape


def facts_of(case: AgentCaseView) -> CaseFacts:
    return CaseFacts(
        amounts={a.amount_id: a for a in case.record.amounts},
        key_dates={k.label: k.date for k in case.metadata.key_dates},
        date_fact_ids={k.label: k.fact_id for k in case.metadata.key_dates},
    )


def _coverage(checklists: list[ExtractedChecklist], views: dict[str, StatuteView], minimum: float) -> float:
    applicable = addressed = 0
    for c in checklists:
        view = views.get(c.statute_id)
        if view is None:
            continue
        for name in ("applicant_eligibility", "mandatory_prerequisites", "statutory_bars", "saving_exceptions"):
            law_items: list[str] = getattr(view.record.diagnostic_checklist, name)
            claimed = {
                i.law_index
                for i in getattr(c.diagnostic_checklist, name)
                if i.law_index is not None and i.confidence >= minimum
            }
            applicable += len(law_items)
            addressed += len(claimed & set(range(len(law_items))))
    return addressed / applicable if applicable else 1.0


class ThemisLocal:
    def __init__(self, llm: LLMClient, prompts: PromptStore, cfg: AppConfig, embedder: Embedder) -> None:
        self._llm = llm
        self._prompts = prompts
        self._cfg = cfg
        self._embedder = embedder

    def check(self, draft: LawyerDraft, ctx: VerifyContext, *, session_id: str) -> Verification:
        claims = claim_ids(draft, ctx.turn)
        out = Verification(claims=claims)
        law = ctx.law
        # Layer 1: the law the argument states, against the dated Law DB and approved predicates (D-062).
        facts = facts_of(ctx.case)
        report = extract_checklists(
            self._llm,
            self._prompts,
            self._cfg,
            draft.text,
            law.views,
            law.predicates,
            facts.amounts,
            session_id=session_id,
        )
        layer1 = run_layer1(
            report.checklists, law.views, law.predicates, facts, self._cfg.themis_local, alternatives=law.alternatives
        )
        out.checklists = report.checklists
        out.hard_errors += [Problem(e.code, f"{e.statute_id}: {e.detail}", e.record_ids) for e in layer1.hard_errors]
        out.warnings += report.warnings + layer1.warnings
        out.rule_coverage = _coverage(report.checklists, law.views, self._cfg.themis_local.extraction_min_confidence)
        # Layer 2.
        l2 = Layer2Result()
        check_claim_references(claims, record_index(ctx.case), set(law.views), l2)
        review_fidelity(
            self._llm,
            self._prompts,
            self._cfg,
            ctx.case,
            draft.text,
            ctx.opponent_last,
            l2,
            session_id=session_id,
        )
        check_citations(self._llm, self._prompts, self._cfg, claims, ctx.fetch_precedent, l2, session_id=session_id)
        check_repetition(self._embedder, draft.text, ctx.own_earlier, self._cfg, l2)
        out.hard_errors += l2.hard_errors
        out.warnings += l2.warnings
        out.assessments = l2.assessments
        out.responsiveness = l2.responsiveness
        return out
