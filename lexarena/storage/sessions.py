"""`sessions` repository and the only code path that moves a session between states.

Each transition belongs to one role: the orchestrator starts, aborts and records the verdict; the
evaluator records the evaluation; reflection records the lessons. A transition is a compare-and-set on
the stored state, so two writers can never both move the same session.
"""

from __future__ import annotations

from typing import Any

from lexarena.schemas.bench import BenchVerdict, JudgeDecision
from lexarena.schemas.session import (
    TRANSITIONS,
    Aggregate,
    Evaluation,
    JudgeScorecard,
    Session,
    SessionState,
    ThemisGlobalReport,
    aggregate_from,
)
from lexarena.storage.errors import NotFoundError, StateTransitionError
from lexarena.storage.mongo import ROOT_NAMESPACE, SESSIONS, MongoDb, Namespace
from lexarena.storage.policy import Op, Principal, Role, Store, require

S = SessionState
TRANSITION_OWNER: dict[tuple[SessionState, SessionState], Role] = {
    (S.CREATED, S.IN_PROGRESS): Role.ORCHESTRATOR,
    (S.CREATED, S.ABORTED): Role.ORCHESTRATOR,
    (S.IN_PROGRESS, S.ABORTED): Role.ORCHESTRATOR,
    (S.IN_PROGRESS, S.VERDICT_RECORDED): Role.ORCHESTRATOR,
    (S.VERDICT_RECORDED, S.EVALUATED): Role.EVALUATOR,
    (S.EVALUATED, S.REFLECTED): Role.REFLECTION,
}


def load_session_state(db: MongoDb, ns: Namespace, session_id: str) -> Session:
    """Read a session for an internal unseal check. Callers are repositories that already passed `require`."""
    doc = ns.collection(db, SESSIONS).find_one({"_id": session_id})
    if doc is None:
        raise NotFoundError(f"session {session_id}")
    return Session.model_validate(doc)


def case_has_sessions(db: MongoDb, ns: Namespace, case_id: str) -> bool:
    """Whether any session, in any state, exists for the case (closes the REVIEW window, D-056)."""
    return ns.collection(db, SESSIONS).count_documents({"case_id": case_id}, limit=1) > 0


class SessionRepository:
    def __init__(self, principal: Principal, db: MongoDb, ns: Namespace = ROOT_NAMESPACE) -> None:
        self._principal = principal
        self._db = db
        self._ns = ns
        self._col = ns.collection(db, SESSIONS)

    def create(self, session: Session) -> None:
        require(self._principal, Store.SESSIONS, Op.WRITE)
        if self._principal.role != Role.ORCHESTRATOR or session.state != S.CREATED:
            raise StateTransitionError("only the orchestrator creates sessions, in state CREATED")
        self._col.insert_one(session.to_document())

    def get(self, session_id: str) -> Session:
        require(self._principal, Store.SESSIONS, Op.READ)
        return load_session_state(self._db, self._ns, session_id)

    def start(self, session_id: str) -> Session:
        return self._transition(session_id, S.IN_PROGRESS, {})

    def abort(self, session_id: str) -> Session:
        return self._transition(session_id, S.ABORTED, {})

    def record_verdict(
        self,
        session_id: str,
        *,
        scorecards: list[JudgeScorecard],
        aggregate: Aggregate,
        winner: str,
        themis_global: ThemisGlobalReport,
    ) -> Session:
        update = {
            "judge_scorecards": scorecards,
            "aggregate": aggregate,
            "winner": winner,
            "themis_global": themis_global,
        }
        return self._transition(session_id, S.VERDICT_RECORDED, update)

    def record_bench_verdict(
        self,
        session_id: str,
        *,
        decisions: list[JudgeDecision],
        bench: BenchVerdict,
        themis_global: ThemisGlobalReport,
    ) -> Session:
        """Record the bench's reasoned decision (D-048). `winner` and `aggregate` are derived from it, never given."""
        update = {
            "judge_decisions": decisions,
            "bench": bench,
            "winner": bench.winner or "UNSTABLE",
            "aggregate": aggregate_from(bench),
            "themis_global": themis_global,
        }
        return self._transition(session_id, S.VERDICT_RECORDED, update)

    def record_evaluation(self, session_id: str, evaluation: Evaluation) -> Session:
        return self._transition(session_id, S.EVALUATED, {"evaluation": evaluation})

    def record_lessons(self, session_id: str, lesson_ids: list[str]) -> Session:
        return self._transition(session_id, S.REFLECTED, {"lessons_written": lesson_ids})

    def _transition(self, session_id: str, target: SessionState, update: dict[str, Any]) -> Session:
        require(self._principal, Store.SESSIONS, Op.WRITE)
        current = load_session_state(self._db, self._ns, session_id)
        if target not in TRANSITIONS[current.state]:
            raise StateTransitionError(f"session {session_id}: {current.state} -> {target} is not allowed")
        owner = TRANSITION_OWNER[(current.state, target)]
        if self._principal.role != owner:
            raise StateTransitionError(f"{current.state} -> {target} is done by {owner}, not {self._principal}")
        # Re-validate the whole document so a transition can never store an inconsistent session.
        updated = Session.model_validate({**current.model_dump(), **update, "state": target})
        result = self._col.replace_one({"_id": session_id, "state": current.state.value}, updated.to_document())
        if result.matched_count != 1:
            raise StateTransitionError(f"session {session_id} changed state concurrently; nothing written")
        return updated
