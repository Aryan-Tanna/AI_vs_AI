"""Sealed repositories: `case_ground_truth` and `judgment_texts` (non-negotiable 6; D-056).

Three independent layers keep sealed data from agents, THEMIS and judges:

1. Credentials: these repositories need a handle on the sealed database, which only offline and post-verdict
   processes can open (`lexarena.storage.factory`); a session process never holds the sealed credentials, and
   MongoDB refuses the shared app user on the sealed database.
2. Role: reads are allowed only to the evaluator and the reflection engine, and to REVIEW, the owner checking a
   clerked case (`policy.POLICY`).
3. State, read from the database and never taken from the caller:
   - evaluator and reflection: `get` names the session it serves, which must be about this case and in
     VERDICT_RECORDED or later;
   - REVIEW: `get_for_review` works only while no session of any state exists for the case, so the review window
     closes for good when the first session is created (Q-019 option A).
   Each path refuses the other role's scope.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from lexarena.schemas.base import StoredModel
from lexarena.schemas.ground_truth import CaseGroundTruth
from lexarena.schemas.judgment import JudgmentText
from lexarena.schemas.session import UNSEALED_STATES
from lexarena.storage.errors import NotFoundError, SealedError
from lexarena.storage.mongo import CASE_GROUND_TRUTH, JUDGMENT_TEXTS, ROOT_NAMESPACE, MongoDb, Namespace
from lexarena.storage.policy import Op, Principal, Scope, Store, require
from lexarena.storage.sessions import case_has_sessions, load_session_state

T = TypeVar("T", bound=StoredModel)


class _SealedRepository(Generic[T]):
    _store: Store
    _collection: str
    _model: type[T]

    def __init__(
        self, principal: Principal, sealed_db: MongoDb, app_db: MongoDb, ns: Namespace = ROOT_NAMESPACE
    ) -> None:
        self._principal = principal
        self._sealed = ns.collection(sealed_db, self._collection)
        self._app_db = app_db
        self._ns = ns

    def put(self, doc: T) -> None:
        require(self._principal, self._store, Op.WRITE)
        data = doc.to_document()
        self._sealed.replace_one({"_id": data["_id"]}, data, upsert=True)

    def _load(self, case_id: str) -> T:
        doc = self._sealed.find_one({"_id": case_id})
        if doc is None:
            raise NotFoundError(f"{self._collection} for case {case_id}")
        return self._model.model_validate(doc)

    def get(self, case_id: str, *, session_id: str) -> T:
        """Evaluator and reflection, after the verdict of a session about this case."""
        if require(self._principal, self._store, Op.READ) != Scope.AFTER_VERDICT:
            raise SealedError(f"{self._principal} may read {self._store} only through its own review window")
        session = load_session_state(self._app_db, self._ns, session_id)
        if session.case_id != case_id:
            raise SealedError(f"session {session_id} is not about case {case_id}")
        if session.state not in UNSEALED_STATES:
            raise SealedError(f"case {case_id} is sealed: session {session_id} is {session.state}")
        return self._load(case_id)

    def get_for_review(self, case_id: str) -> T:
        """REVIEW only, and only while the case has no session of any state."""
        if require(self._principal, self._store, Op.READ) != Scope.BEFORE_FIRST_SESSION:
            raise SealedError(f"{self._principal} has no review window on {self._store}")
        if case_has_sessions(self._app_db, self._ns, case_id):
            raise SealedError(f"case {case_id} has a session: the review window is closed")
        return self._load(case_id)


class GroundTruthRepository(_SealedRepository[CaseGroundTruth]):
    _store = Store.CASE_GROUND_TRUTH
    _collection = CASE_GROUND_TRUTH
    _model = CaseGroundTruth


class JudgmentTextRepository(_SealedRepository[JudgmentText]):
    _store = Store.JUDGMENT_TEXT
    _collection = JUDGMENT_TEXTS
    _model = JudgmentText
