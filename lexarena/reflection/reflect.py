"""The reflection engine for one evaluated session (BUILD_PLAN Step 12; ARCHITECTURE §6; SPEC F1-F7; D-077).

Runs only in the sealed process as REFLECTION, after EVALUATED, and only in LEARN runs (the run manager never starts
it otherwise). In order:
1. Lessons pinned into this session are updated with the session's rewards (SPEC F2, F4): a lawyer lesson with the
   reward of the side whose party status it serves (rebuttal depth, share of turns not FLAGGED, mean THEMIS score), a
   judge lesson with the bench's issue alignment.
2. The reflection model proposes lessons from the court's LAW and MIXED findings, the bench's holdings and each side's
   argument and verifier record. Every candidate passes the code checks in filters.py or is rejected with a reason.
3. Survivors are deduplicated against the memory (dedup.py) and stored; the session moves to REFLECTED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import fmean

from lexarena.embedding import Embedder
from lexarena.llm.client import LLMClient
from lexarena.memory.weights import after_use
from lexarena.prompts import PromptStore
from lexarena.reflection.dedup import Placement, place
from lexarena.reflection.filters import Context, check
from lexarena.schemas.base import SIDES, Side
from lexarena.schemas.config import AppConfig
from lexarena.schemas.ground_truth import CaseGroundTruth
from lexarena.schemas.lesson import Lesson
from lexarena.schemas.reflection import CompareVerdict, LessonCandidates
from lexarena.schemas.session import Session, SessionState
from lexarena.schemas.transcript import PrivateTurnData, PublishedTurn
from lexarena.storage.factory import ReflectionStores
from lexarena.storage.lessons import LessonRepository, lesson_text
from lexarena.storage.transcript import PrivateTurnRepository

ROLE = "reflection"
EXCLUDED_DRIVER = "EVIDENCE"


class NotReflectableError(RuntimeError):
    """The session is not EVALUATED, or has no bench verdict."""


@dataclass
class ReflectionResult:
    session: Session
    written: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    placements: list[str] = field(default_factory=list)
    rewards: dict[str, float | None] = field(default_factory=dict)


def side_reward(side: Side, session: Session, private: list[PrivateTurnData]) -> float | None:
    """SPEC F2 for a lawyer: answering the opponent, avoiding THEMIS failures, THEMIS score. Outcome is not in it."""
    parts: list[float] = []
    rebuttal = session.themis_global.rebuttal_depth.get(side) if session.themis_global else None
    if isinstance(rebuttal, dict) and isinstance(rebuttal.get("depth"), float | int):
        parts.append(float(rebuttal["depth"]))
    if private:
        parts.append(1 - sum(p.themis_local.outcome == "FLAGGED" for p in private) / len(private))
        parts.append(fmean(p.themis_local.s_local for p in private))
    return fmean(parts) if parts else None


def _findings(truth: CaseGroundTruth) -> str:
    out = []
    for f in truth.issue_findings:
        if f.driver == EXCLUDED_DRIVER:
            continue
        out.append(
            f"[{f.issue_id}] ({f.driver}) favours {f.favours}: {f.finding}\n    test: {f.test_applied}\n"
            f"    decisive: {' | '.join(f.decisive_points) or '-'}\n"
            f"    authorities: {', '.join(f.authorities_relied_on) or '-'}\n"
            f"    source_paras: {', '.join(f.source_paras)}"
        )
    return "\n".join(out) or "(none: every finding turned on evidence)"


def _side_block(side: Side, turns: list[PublishedTurn], private: list[PrivateTurnData], session: Session) -> str:
    claims = [f"- T{t.turn} {c.type}: {c.text}" for t in turns if t.speaker == side for c in t.claims]
    codes = sorted({code for p in private for attempt in p.themis_local.hard_errors_by_attempt for code in attempt})
    flagged = sum(p.themis_local.outcome == "FLAGGED" for p in private)
    rebuttal = session.themis_global.rebuttal_depth.get(side) if session.themis_global else None
    return "\n".join(
        [
            "Claims made:",
            *(claims or ["- (none)"]),
            f"Verifier error codes incurred (each turn, any attempt): {', '.join(codes) or 'none'}",
            f"Turns published FLAGGED: {flagged} of {len(private)}",
            f"Rebuttal record: {rebuttal if rebuttal is not None else '-'}",
        ]
    )


class Reflection:
    def __init__(self, llm: LLMClient, prompts: PromptStore, cfg: AppConfig, embedder: Embedder) -> None:
        self._llm = llm
        self._prompts = prompts
        self._cfg = cfg
        self._embedder = embedder

    def _compare(self, a: Lesson, b: Lesson, session_id: str) -> str:
        ref = self._cfg.prompts.reflection_compare
        prompt = self._prompts.render(
            ref.id, ref.version, trigger_a=a.trigger, lesson_a=a.lesson, trigger_b=b.trigger, lesson_b=b.lesson
        )
        verdict = self._llm.complete_json(role=ROLE, user=prompt, schema=CompareVerdict, session_id=session_id)
        return verdict.value.relation

    def reflect(
        self,
        stores: ReflectionStores,
        private_for: dict[Side, PrivateTurnRepository],
        session_id: str,
        *,
        run_id: str,
    ) -> ReflectionResult:
        session = stores.sessions.get(session_id)
        if session.state != SessionState.EVALUATED or session.bench is None or session.evaluation is None:
            raise NotReflectableError(f"session {session_id} is {session.state}; reflection follows evaluation")
        case = stores.cases.get(session.case_id)
        truth = stores.ground_truth.get(session.case_id, session_id=session_id)
        turns = stores.transcript.turns(session_id)
        private = {side: private_for[side].for_side(session_id, side) for side in SIDES}
        case_seq = session.case_seq or 1
        result = ReflectionResult(session=session)
        rewards: dict[str, float | None] = {side: side_reward(side, session, private[side]) for side in SIDES}
        rewards["BENCH"] = session.evaluation.issue_alignment
        result.rewards = rewards
        status_of: dict[str, str] = {
            side: next(p.status for p in case.agent_view.parties if p.simulation_side == side) for side in SIDES
        }
        memories: dict[str, LessonRepository] = {"LAWYER": stores.lawyer_memory, "JUDGE": stores.judge_memory}
        dim = len(self._embedder.embed(["dimension probe"])[0])
        for repo in memories.values():
            repo.ensure_collection(dim)

        # 1. Lessons used in this session learn from how it went.
        pinned = set(session.pinned_lessons)
        for repo in memories.values():
            for lesson, vector in repo.with_vectors():
                if lesson.lesson_id not in pinned:
                    continue
                if lesson.memory == "JUDGE":
                    reward = rewards["BENCH"]
                else:
                    served = [s for s in SIDES if status_of[s] == lesson.party_status]
                    values = [r for s in served if (r := rewards[s]) is not None]
                    reward = max(values) if values else None
                if reward is not None:
                    repo.upsert(after_use(lesson, reward, case_seq, self._cfg.memory), vector)
                    result.updated.append(lesson.lesson_id)

        # 2. New lessons.
        ref = self._cfg.prompts.reflection_lessons
        held = {f.issue_id: f.upholds or "UNSTABLE" for f in session.bench.issue_findings}
        bench_text = "\n".join(f"[{i}] upheld {u}" for i, u in held.items())
        bench_text += f"\nOverall: {session.bench.winner or 'UNSTABLE'}"
        prompt = self._prompts.render(
            ref.id,
            ref.version,
            findings=_findings(truth),
            statutes="\n".join(f"[{a.statute_id}] {a.interpretation}" for a in truth.statutory_analysis) or "-",
            bench=bench_text,
            petitioner_status=status_of["PETITIONER"],
            respondent_status=status_of["RESPONDENT"],
            petitioner=_side_block("PETITIONER", turns, private["PETITIONER"], session),
            respondent=_side_block("RESPONDENT", turns, private["RESPONDENT"], session),
            max_lessons=str(self._cfg.memory.max_lessons_per_case),
        )
        candidates = self._llm.complete_json(
            role=ROLE, user=prompt, schema=LessonCandidates, session_id=session_id
        ).value.lessons[: self._cfg.memory.max_lessons_per_case]
        av = case.agent_view
        ctx = Context(
            case_id=case.id,
            run_id=run_id,
            truth=truth,
            party_status=status_of,
            names=[*truth.anonymization_map, *truth.anonymization_map.values(), *(p.pseudonym for p in av.parties)],
            generic_name_words={w.lower() for w in self._cfg.clerk.generic_name_words},
            base_rate_markers=self._cfg.memory.base_rate_markers,
            known_statutes={*av.metadata.statutes_invoked, *(a.statute_id for a in truth.statutory_analysis)},
            errors_by_side={
                side: {c for p in private[side] for attempt in p.themis_local.hard_errors_by_attempt for c in attempt}
                for side in SIDES
            },
            initial_confidence=self._cfg.memory.initial_confidence,
            case_seq=case_seq,
        )
        accepted: list[Lesson] = []
        for n, candidate in enumerate(candidates, 1):
            verdict = check(candidate, n, ctx)
            if verdict.lesson is None:
                result.rejected.append(f"candidate {n}: {verdict.reason}")
            else:
                accepted.append(verdict.lesson)

        # 3. Deduplicate and store.
        vectors = self._embedder.embed([lesson_text(x) for x in accepted]) if accepted else []
        for lesson, vector in zip(accepted, vectors, strict=True):
            repo = memories[lesson.memory]
            placement: Placement = place(
                lesson, vector, repo.with_vectors(), lambda a, b: self._compare(a, b, session_id), self._cfg.memory
            )
            for stored, stored_vector in placement.writes:
                repo.upsert(stored, stored_vector)
            result.placements.append(f"{lesson.lesson_id}: {placement.outcome}")
            result.written += [stored.lesson_id for stored, _ in placement.writes]
        ids = sorted({*result.written, *result.updated})
        result.session = stores.sessions.record_lessons(session_id, ids)
        return result
