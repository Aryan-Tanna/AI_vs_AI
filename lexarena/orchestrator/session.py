"""One session, end to end (BUILD_PLAN Step 9; ARCHITECTURE §4, §5; SPEC E6, I2, I3-10; D-073, D-077-D-079).

Runs in the session process with session credentials only. In order:
1. Load the full case (the orchestrator role may; it never passes the simulation date, build data or split into a
   prompt: lawyers, THEMIS and judges receive `AgentCaseView`) and fix its scope (date cut-off, exclusions).
2. Resolve the law once on the case dates (`LawContext`): the regulation memory both sides, THEMIS and the bench use.
3. Pin lessons (unless the memory mode is EMPTY or the NO_MEMORY ablation is on), the same way for both sides; record
   their IDs on the session. Pinning only reads.
4. Create and start the session, stamped with code, config, Law DB, precedent DB and memory versions.
5. Private strategy phase for each side (D-053).
6. Turns 1..`session.alternating_turns`, LEX-P first; then the two closings, both drafted against the transcript
   through the last alternating turn and published only after both are verified, so neither sees the other's (E6).
   Every draft passes THEMIS-LOCAL with retries (SPEC D8) unless the NO_THEMIS ablation is on.
7. THEMIS-GLOBAL audits the transcript; the bench decides; the verdict is recorded; session memory is cleared.
Any failure aborts the session, so a re-run starts a new one (LLM calls already made come from the cache).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from lexarena.agents.knowledge import CaseLibrary, ExperienceBase, LawyerKnowledge, RegulationMemory
from lexarena.agents.lawyer import Lawyer
from lexarena.embedding import Embedder
from lexarena.judges.personas import PersonaRegistry
from lexarena.judges.run import Bench, BenchInputs, law_for_bench
from lexarena.llm.client import LLMClient
from lexarena.memory.pinning import select
from lexarena.prompts import PromptStore
from lexarena.retrieval.tools import PrecedentReader, RetrievalTools
from lexarena.schemas.agent import LawyerDraft
from lexarena.schemas.base import SIDES, Side
from lexarena.schemas.config import AppConfig
from lexarena.schemas.retrieval import CaseScope
from lexarena.schemas.run import MemoryMode
from lexarena.schemas.session import Session, SessionConfig, SessionState, VersionStamp
from lexarena.schemas.statute_alias import StatuteAliasTable
from lexarena.schemas.transcript import (
    PrivateTurnData,
    PublicClaim,
    PublishedTurn,
    ThemisLocalResult,
    ThemisWarning,
    turn_document_id,
)
from lexarena.storage.factory import SessionProcess
from lexarena.storage.policy import Role
from lexarena.storage.temporal import AsOf
from lexarena.themis_global.audit import audit_transcript
from lexarena.themis_local.outcome import VerifiedTurn, verify_with_retries
from lexarena.themis_local.verify import ThemisLocal, Verification, VerifyContext, claim_ids
from lexarena.versioning import combine, precedent_snapshot

OPENING, REBUTTAL, CLOSING = "OPENING", "REBUTTAL", "CLOSING"
NO_THEMIS, NO_MEMORY, NO_EXHIBIT_CARDS = "NO_THEMIS", "NO_MEMORY", "NO_EXHIBIT_CARDS"
THEMIS_DISABLED = "THEMIS_DISABLED"
TURN_PREFIX = "TURN:"
NOTES_PREFIX = "NOTES:"
SESSION_SUFFIX = 6  # literal-ok: random hex characters that keep re-runs of one case apart


@dataclass(frozen=True)
class SessionOptions:
    run_id: str
    mode: MemoryMode
    case_seq: int
    ablations: frozenset[str] = frozenset()
    allow_draft_personas: bool = False


@dataclass
class Services:
    llm: LLMClient
    prompts: PromptStore
    cfg: AppConfig
    embedder: Embedder
    aliases: StatuteAliasTable
    personas: PersonaRegistry
    git_sha: str
    config_sha256: str
    log: Callable[[str], None] = field(default=lambda _: None)


def schedule(cfg: AppConfig) -> list[tuple[int, Side, str]]:
    """Alternating turns, LEX-P first; then one closing each (published after both are written)."""
    n = cfg.session.alternating_turns
    turns: list[tuple[int, Side, str]] = [
        (t, SIDES[(t - 1) % len(SIDES)], OPENING if t <= len(SIDES) else REBUTTAL) for t in range(1, n + 1)
    ]
    if cfg.session.parallel_closings:
        turns += [(n + 1 + i, side, CLOSING) for i, side in enumerate(SIDES)]
    return turns


def _no_themis(draft: LawyerDraft, turn: int) -> VerifiedTurn:
    v = Verification(claims=claim_ids(draft, turn))
    result = ThemisLocalResult(
        outcome="PASS_WITH_NOTES",
        attempts=1,
        hard_errors_by_attempt=[[]],
        warnings=[ThemisWarning(code=THEMIS_DISABLED, detail="NO_THEMIS ablation")],
        s_local=0.0,
    )
    return VerifiedTurn(draft=draft, verification=v, result=result, flags=[])


def run_session(proc: SessionProcess, case_id: str, opts: SessionOptions, svc: Services) -> Session:
    cfg = svc.cfg
    orch = proc.orchestrator()
    full = orch.cases.get(case_id)
    scope = CaseScope.from_case(full)
    as_of = AsOf.for_case(full)
    session_id = f"{case_id}_{opts.run_id}_{uuid.uuid4().hex[:SESSION_SUFFIX]}"
    judge_stores = proc.judge(scope)
    case = judge_stores.case.agent_view(case_id)
    law = law_for_bench(case, [], orch.law, as_of, cfg)
    statutes = set(law.views)

    # Experience base: read only, same selection rule and budget for both sides (E6, F6).
    use_memory = opts.mode != "EMPTY" and NO_MEMORY not in opts.ablations
    lawyer_pool = orch.lawyer_memory.all() if use_memory else []
    judge_pool = orch.judge_memory.all() if use_memory else []
    status_of = {s: next(p.status for p in case.parties if p.simulation_side == s) for s in SIDES}
    pinned = {
        s: select(lawyer_pool, party_status=status_of[s], statutes=statutes, case_seq=opts.case_seq, cfg=cfg)
        for s in SIDES
    }
    judge_lessons = select(judge_pool, party_status=None, statutes=statutes, case_seq=opts.case_seq, cfg=cfg)
    pinned_ids = sorted({x.lesson_id for ls in pinned.values() for x in ls} | {x.lesson_id for x in judge_lessons})

    versions = VersionStamp(
        git_sha=svc.git_sha,
        config_version=cfg.version,
        config_sha256=svc.config_sha256,
        law_db_snapshot=orch.law.snapshot(),
        precedent_db_snapshot=precedent_snapshot(orch.precedents.stored_hashes()),
        memory_snapshot=combine(orch.lawyer_memory.snapshot(), orch.judge_memory.snapshot()),
    )
    session = Session.model_validate(
        {
            "_id": session_id,
            "case_id": case_id,
            "split": full.split,
            "state": SessionState.CREATED,
            "versions": versions.model_dump(),
            "config": SessionConfig(
                lawyer_model=cfg.models.lawyer.name, judge_model=cfg.models.judge.name, seed=cfg.seed
            ).model_dump(),
            "themis_global": None,
            "judge_scorecards": [],
            "aggregate": None,
            "winner": None,
            "evaluation": None,
            "lessons_written": [],
            "case_seq": opts.case_seq,
            "pinned_lessons": pinned_ids,
        }
    )
    orch.sessions.create(session)
    try:
        orch.sessions.start(session_id)

        def tools(reader: PrecedentReader, known: set[str]) -> RetrievalTools:
            return RetrievalTools(
                reader=reader,
                case=case,
                embedder=svc.embedder,
                reranker=None,
                known_statutes=known,
                aliases=svc.aliases,
                top_k=cfg.retrieval.top_k,
                candidate_pool=cfg.retrieval.candidate_pool,
                card_text_tokens=cfg.retrieval.card_text_tokens,
                query_instruction=cfg.embedding.query_instruction,
            )

        lawyers: dict[Side, Lawyer] = {}
        themis: dict[Side, tuple[ThemisLocal, CaseLibrary]] = {}
        stores = {s: (proc.lawyer(s, session_id, scope), proc.themis_local(s, session_id, scope)) for s in SIDES}
        for side in SIDES:
            lawyer_stores, themis_stores = stores[side]
            known = lawyer_stores.law.statute_ids()
            library = CaseLibrary.for_role(Role.LAWYER, tools(lawyer_stores.precedents, known))
            knowledge = LawyerKnowledge(RegulationMemory(law), library, ExperienceBase(pinned[side]))
            lawyers[side] = Lawyer(
                side,
                case,
                knowledge,
                svc.llm,
                svc.prompts,
                cfg,
                session_id=session_id,
                exhibit_contents=NO_EXHIBIT_CARDS not in opts.ablations,
            )
            fetch_lib = CaseLibrary.for_role(
                Role.THEMIS_LOCAL,
                tools(themis_stores.precedents, known),
            )
            themis[side] = (ThemisLocal(svc.llm, svc.prompts, cfg, svc.embedder), fetch_lib)

        for side in SIDES:  # private strategy phase, same budget for both
            notes = lawyers[side].prepare()
            stores[side][0].memory.append(NOTES_PREFIX + notes.model_dump_json())
            svc.log(f"{side} prepared: {len(lawyers[side].held)} authorities held")

        published: list[PublishedTurn] = []

        def verified(turn: int, side: Side, turn_type: str, upto: list[PublishedTurn]) -> VerifiedTurn:
            lawyer = lawyers[side]
            own = [
                i.removeprefix(TURN_PREFIX) for i in stores[side][1].agent_memory.items() if i.startswith(TURN_PREFIX)
            ]
            others = [t for t in upto if t.speaker != side]
            checker, library = themis[side]
            ctx = VerifyContext(
                case=case,
                law=law,
                fetch_precedent=library.tools["get_precedent"],
                turn=turn,
                opponent_last=others[-1].published_text if others else None,
                own_earlier=own,
            )

            def write(feedback: str | None) -> LawyerDraft:
                return lawyer.draft(turn, turn_type, upto, feedback)[0]

            if NO_THEMIS in opts.ablations:
                return _no_themis(write(None), turn)
            return verify_with_retries(write, lambda d: checker.check(d, ctx, session_id=session_id), cfg.themis_local)

        def publish(turn: int, side: Side, turn_type: str, vt: VerifiedTurn) -> None:
            framed = {i.issue_id for i in case.framed_issues}
            pub = PublishedTurn.model_validate(
                {
                    "_id": turn_document_id(session_id, turn),
                    "case_id": case_id,
                    "session_id": session_id,
                    "turn": turn,
                    "speaker": side,
                    "turn_type": turn_type,
                    "issues_addressed": [i for i in dict.fromkeys(vt.draft.issues_addressed) if i in framed],
                    "published_text": vt.draft.text,
                    "claims": [
                        PublicClaim(
                            claim_id=cid,
                            type=c.type,
                            text=c.text or "(empty)",
                            record_ids=[r for r in c.record_ids if r],
                            statute_id=c.statute_id or None,
                            precedent_ids=[p for p in c.precedent_ids if p],
                        ).model_dump()
                        for cid, c in vt.verification.claims
                    ],
                    "visible_flags": [f.model_dump() for f in vt.flags],
                    "created_at": datetime.now(UTC),
                }
            )
            orch.transcript.publish(pub)
            stores[side][1].private_turns.put(
                PrivateTurnData(
                    id=turn_document_id(session_id, turn),
                    case_id=case_id,
                    session_id=session_id,
                    turn=turn,
                    side=side,
                    themis_local=vt.result,
                    claim_assessments=vt.verification.assessments,
                    statute_checklists=vt.verification.checklists,
                )
            )
            stores[side][0].memory.append(TURN_PREFIX + vt.draft.text)
            published.append(pub)
            svc.log(f"turn {turn} {side} {turn_type}: {vt.result.outcome} after {vt.result.attempts} attempt(s)")

        plan = schedule(cfg)
        closings = [(turn, side, kind) for turn, side, kind in plan if kind == CLOSING]
        for turn, side, kind in plan:
            if kind != CLOSING:
                publish(turn, side, kind, verified(turn, side, kind, list(published)))
        through = list(published)  # both closings see the same transcript and not each other (E6)
        written = [(turn, side, verified(turn, side, CLOSING, through)) for turn, side, _ in closings]
        for turn, side, vt in written:
            publish(turn, side, CLOSING, vt)

        audit = audit_transcript(svc.llm, svc.prompts, cfg, case, published, session_id=session_id)
        bench_law = law_for_bench(case, published, orch.law, as_of, cfg)
        bench = Bench(svc.llm, svc.prompts, cfg, svc.personas, allow_unapproved_personas=opts.allow_draft_personas)
        judge_library = CaseLibrary.for_role(
            Role.JUDGE,
            tools(judge_stores.precedents, set()),
        )
        result = bench.decide(
            BenchInputs(
                case=case,
                turns=published,
                law=bench_law,
                fetch_precedent=judge_library.tools["get_precedent"],
                audit=audit,
                lessons=judge_lessons,
            ),
            session_id=session_id,
        )
        svc.log(json.dumps({"bench": result.verdict.status, "winner": result.verdict.winner, "notes": result.notes}))
        return orch.sessions.record_bench_verdict(
            session_id, decisions=result.decisions, bench=result.verdict, themis_global=audit
        )
    except BaseException:
        current = orch.sessions.get(session_id)
        if current.state in (SessionState.CREATED, SessionState.IN_PROGRESS):
            orch.sessions.abort(session_id)
        raise
    finally:
        orch.session_memory.clear_session(session_id)
