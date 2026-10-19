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
from pathlib import Path

from lexarena import trace
from lexarena.agents.desk import KnowledgeDesk
from lexarena.agents.knowledge import CaseLibrary, ExperienceBase, LawyerKnowledge, RegulationMemory
from lexarena.agents.lawyer import Lawyer
from lexarena.embedding import Embedder
from lexarena.judges.personas import PersonaRegistry
from lexarena.judges.run import Bench, BenchInputs, StatuteSource, law_for_bench
from lexarena.llm.client import LLMClient
from lexarena.memory.pinning import lesson_line, pin, usable
from lexarena.prompts import PromptStore
from lexarena.retrieval.tools import PrecedentReader, RetrievalTools
from lexarena.schemas.agent import LawyerDraft
from lexarena.schemas.base import SIDES, Side
from lexarena.schemas.config import AppConfig
from lexarena.schemas.lesson import Lesson
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
from lexarena.statute_ids import resolve_statute_id
from lexarena.storage.factory import SessionProcess
from lexarena.storage.policy import Role
from lexarena.storage.temporal import AsOf, StatuteView
from lexarena.themis_global.audit import audit_transcript
from lexarena.themis_local.layer2 import WARN_REPETITION as REPETITION_WARNING
from lexarena.themis_local.outcome import VerifiedTurn, verify_with_retries
from lexarena.themis_local.verify import LawContext, ThemisLocal, Verification, VerifyContext, claim_ids
from lexarena.versioning import combine, law_versions, precedent_snapshot

OPENING, REBUTTAL, CLOSING = "OPENING", "REBUTTAL", "CLOSING"
NO_THEMIS, NO_MEMORY, NO_EXHIBIT_CARDS = "NO_THEMIS", "NO_MEMORY", "NO_EXHIBIT_CARDS"
NO_CASE_LIBRARY, NO_LOOKUPS = "NO_CASE_LIBRARY", "NO_LOOKUPS"  # D-153: per-store ablations, both sides alike
THEMIS_DISABLED = "THEMIS_DISABLED"
TURN_PREFIX = "TURN:"
NOTES_PREFIX = "NOTES:"
ABORT_CHARS = 2000  # literal-ok: how much of an abort's message the trace keeps
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
    trace_dir: Path | None = None  # the owner's session trace (D-110); None: no trace


def statute_resolver(
    source: StatuteSource, as_of: AsOf, known: set[str], aliases: StatuteAliasTable, side_law: LawContext
) -> Callable[[str], StatuteView | None]:
    """A STATUTE lookup (D-112): the cited name resolved by the ingestion rules, then the provision as it stood on the
    case dates (server-side; the agent never gets the dates). Found provisions bring their approved predicates."""

    def resolve(cited: str) -> StatuteView | None:
        sid = cited.strip() if cited.strip() in known else resolve_statute_id(cited, known, aliases)[0]
        if sid is None:
            return None
        view = source.get_statute(sid, as_of)
        if view is not None and sid not in side_law.predicates:
            side_law.predicates[sid] = source.predicates(sid)
        return view

    return resolve


def lesson_search(pool: list[Lesson], *, exclude: set[str], embedder: Embedder) -> Callable[[str, int], list[Lesson]]:
    """A LESSONS lookup (D-112): the side's usable lessons not already pinned, ranked by meaning against the query."""
    candidates = [x for x in pool if x.lesson_id not in exclude]
    vectors = embedder.embed([lesson_line(x) for x in candidates]) if candidates else []

    def search(query: str, k: int) -> list[Lesson]:
        if not candidates:
            return []
        q = embedder.embed([query])[0]
        scored = sorted(zip(candidates, vectors, strict=True), key=lambda cv: (-_dot(q, cv[1]), cv[0].lesson_id))
        return [c for c, _ in scored[:k]]

    return search


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


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
    session_id = f"{case_id}_{opts.run_id}_{uuid.uuid4().hex[:SESSION_SUFFIX]}"
    with trace.session_trace(svc.trace_dir, session_id):
        return _run_session(proc, case_id, opts, svc, session_id)


def _run_session(proc: SessionProcess, case_id: str, opts: SessionOptions, svc: Services, session_id: str) -> Session:
    cfg = svc.cfg
    orch = proc.orchestrator()
    full = orch.cases.get(case_id)
    scope = CaseScope.from_case(full)
    as_of = AsOf.for_case(full)
    hearing_year = full.agent_view.metadata.simulation_date.year  # D-144: only the year reaches any prompt
    judge_stores = proc.judge(scope)
    case = judge_stores.case.agent_view(case_id)
    law = law_for_bench(case, [], orch.law, as_of, cfg)
    # D-139: appeal provisions attach to every appeal, so they never decide which lessons a case gets.
    unkeyed = orch.law.statute_ids_of_types(cfg.memory.unkeyed_jurisdiction_types)
    statutes = set(law.views)
    lesson_statutes = statutes - unkeyed
    families = cfg.memory.family_of()

    # Experience base: read only, same selection rule and budget for both sides (E6, F6).
    use_memory = opts.mode != "EMPTY" and NO_MEMORY not in opts.ablations
    lawyer_pool = orch.lawyer_memory.all() if use_memory else []
    judge_pool = orch.judge_memory.all() if use_memory else []
    status_of = {s: next(p.status for p in case.parties if p.simulation_side == s) for s in SIDES}
    law_seen = law_versions(law.views)  # D-111: lessons are pinned only under the same law
    picks = {
        s: pin(
            lawyer_pool,
            party_status=status_of[s],
            statutes=lesson_statutes,
            case_seq=opts.case_seq,
            cfg=cfg,
            law_versions=law_seen,
            unkeyed=unkeyed,
        )
        for s in SIDES
    }
    judge_pick = pin(
        judge_pool,
        party_status=None,
        statutes=lesson_statutes,
        case_seq=opts.case_seq,
        cfg=cfg,
        law_versions=law_seen,
        unkeyed=unkeyed,
    )
    pinned = {s: picks[s].all for s in SIDES}
    judge_lessons = judge_pick.all
    pinned_ids = sorted({x.lesson_id for ls in pinned.values() for x in ls} | {x.lesson_id for x in judge_lessons})
    explored_ids = sorted({x.lesson_id for p in [*picks.values(), judge_pick] for x in p.explore})

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
            "pinned_by_side": {s: [x.lesson_id for x in pinned[s]] for s in SIDES},
            "explored_lessons": explored_ids,
            "law_versions": law_seen,
        }
    )
    orch.sessions.create(session)
    # The owner's trace (D-110): the agent view exactly as the agents get it (pseudonymised, decision date removed by
    # the repository), never sealed data; no model reads it.
    trace.event(
        "case_opened",
        case_id=case_id,
        run_id=opts.run_id,
        mode=opts.mode,
        case_seq=opts.case_seq,
        ablations=sorted(opts.ablations),
        agent_view=case.model_dump(mode="json"),
        statutes=sorted(statutes),
        lessons={s: [x.model_dump(mode="json") for x in pinned[s]] for s in SIDES},
        explored=explored_ids,
        judge_lessons=[x.model_dump(mode="json") for x in judge_lessons],
        models={"lawyer": cfg.models.lawyer.name, "judge": cfg.models.judge.name, "verifier": cfg.models.verifier.name},
    )
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
                card_facts_tokens=cfg.retrieval.card_facts_tokens,
                card_cited_max=cfg.retrieval.card_cited_max,
                query_instruction=cfg.embedding.query_instruction,
            )

        lawyers: dict[Side, Lawyer] = {}
        themis: dict[Side, tuple[ThemisLocal, CaseLibrary]] = {}
        stores = {s: (proc.lawyer(s, session_id, scope), proc.themis_local(s, session_id, scope)) for s in SIDES}
        # D-112: each side's own copy of the law, so a statute one side looks up joins only its regulation memory (and
        # its THEMIS checks it); both copies start identical.
        side_law = {
            s: LawContext(views=dict(law.views), alternatives=law.alternatives, predicates=dict(law.predicates))
            for s in SIDES
        }
        for side in SIDES:
            lawyer_stores, themis_stores = stores[side]
            known = lawyer_stores.law.statute_ids()
            library = (
                CaseLibrary.closed()
                if NO_CASE_LIBRARY in opts.ablations
                else CaseLibrary.for_role(Role.LAWYER, tools(lawyer_stores.precedents, known))
            )
            knowledge = LawyerKnowledge(RegulationMemory(side_law[side]), library, ExperienceBase(pinned[side]))
            desk = KnowledgeDesk(
                statute=statute_resolver(orch.law, as_of, known, svc.aliases, side_law[side]),
                library=library,
                lessons=lesson_search(
                    usable(
                        lawyer_pool,
                        party_status=status_of[side],
                        statutes=lesson_statutes,
                        law_versions=law_seen,
                        families=families,
                        unkeyed=unkeyed,
                    ),
                    exclude={x.lesson_id for x in pinned[side]},
                    embedder=svc.embedder,
                ),
                cfg=cfg,
            )
            lawyers[side] = Lawyer(
                side,
                case,
                knowledge,
                svc.llm,
                svc.prompts,
                cfg,
                session_id=session_id,
                exhibit_contents=NO_EXHIBIT_CARDS not in opts.ablations,
                desk=None if NO_LOOKUPS in opts.ablations else desk,
                hearing_year=hearing_year,
            )
            fetch_lib = CaseLibrary.for_role(
                Role.THEMIS_LOCAL,
                tools(themis_stores.precedents, known),
            )
            themis[side] = (ThemisLocal(svc.llm, svc.prompts, cfg, svc.embedder), fetch_lib)

        for side in SIDES:  # private strategy phase, same budget for both
            with trace.tags(phase="PREPARE", side=side):
                notes = lawyers[side].prepare()
                trace.event(
                    "prepared",
                    notes=notes.model_dump(mode="json"),
                    held=[c.model_dump(mode="json") for c in lawyers[side].held],
                )
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
                law=side_law[side],
                fetch_precedent=library.tools["get_precedent"],
                turn=turn,
                opponent_last=others[-1].published_text if others else None,
                own_earlier=own,
                closing=turn_type == CLOSING,
            )

            def write(feedback: str | None) -> LawyerDraft:
                return lawyer.draft(turn, turn_type, upto, feedback)[0]

            with trace.tags(phase="TURN", side=side, turn=turn, turn_type=turn_type):
                if NO_THEMIS in opts.ablations:
                    return _no_themis(write(None), turn)
                return verify_with_retries(
                    write,
                    lambda d, last: checker.check(d, ctx, session_id=session_id, short_circuit=not last),
                    cfg.themis_local,
                )

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
            trace.event(
                "turn_published",
                side=side,
                turn=turn,
                turn_type=turn_type,
                published=pub.model_dump(mode="json", by_alias=True),
                themis_local=vt.result.model_dump(mode="json"),
            )
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
            # D-135: this side's own repetition warning goes to this side's next submission only.
            repeated = [w.detail for w in vt.result.warnings if w.code == REPETITION_WARNING and w.detail]
            lawyers[side].repetition_note = "; ".join(repeated) or None
            if turn_type != CLOSING:  # D-112: answered before this side's next submission; a closing has none
                answers = lawyers[side].answer_lookups(vt.draft)
                trace.event(
                    "lookups", side=side, turn=turn, asked=[x.model_dump() for x in vt.draft.lookups], answers=answers
                )
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

        with trace.tags(phase="AUDIT"):
            audit = audit_transcript(svc.llm, svc.prompts, cfg, case, published, session_id=session_id)
            trace.event("audit", report=audit.model_dump(mode="json"))
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
                hearing_year=hearing_year,
                desk=KnowledgeDesk(  # D-112: statutes and the bench's own lessons; no search (SPEC I3)
                    statute=statute_resolver(orch.law, as_of, orch.law.statute_ids(), svc.aliases, bench_law),
                    library=judge_library,
                    lessons=lesson_search(
                        usable(
                            judge_pool,
                            party_status=None,
                            statutes=lesson_statutes,
                            law_versions=law_seen,
                            unkeyed=unkeyed,
                        ),
                        exclude={x.lesson_id for x in judge_lessons},
                        embedder=svc.embedder,
                    ),
                    cfg=cfg,
                ),
            ),
            session_id=session_id,
        )
        svc.log(json.dumps({"bench": result.verdict.status, "winner": result.verdict.winner, "notes": result.notes}))
        trace.event("verdict", verdict=result.verdict.model_dump(mode="json"), notes=result.notes)
        return orch.sessions.record_bench_verdict(
            session_id, decisions=result.decisions, bench=result.verdict, themis_global=audit
        )
    except BaseException as exc:
        trace.event("aborted", error=f"{type(exc).__name__}: {exc}"[:ABORT_CHARS])
        current = orch.sessions.get(session_id)
        if current.state in (SessionState.CREATED, SessionState.IN_PROGRESS):
            orch.sessions.abort(session_id)
        raise
    finally:
        orch.session_memory.clear_session(session_id)
