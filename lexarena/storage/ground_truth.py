"""`case_ground_truth` repository (non-negotiable 6).

Three independent layers keep ground truth from agents, THEMIS and judges:

1. Credentials: this repository needs a handle on the sealed database, which only offline and
   post-verdict processes can open (`lexarena.storage.factory`); a session process never holds the
   sealed credentials, and MongoDB refuses the shared app user on the sealed database.
2. Role: reads are allowed only to the evaluator and the reflection engine (`policy.POLICY`).
3. State: a read names the session it serves; the session's stored state, read from the database and
   never taken from the caller, must be VERDICT_RECORDED or later, and the session must be about this case.
"""

from __future__ import annotations

from lexarena.schemas.ground_truth import CaseGroundTruth
from lexarena.schemas.session import UNSEALED_STATES
from lexarena.storage.errors import NotFoundError, SealedError
from lexarena.storage.mongo import CASE_GROUND_TRUTH, ROOT_NAMESPACE, MongoDb, Namespace
from lexarena.storage.policy import Op, Principal, Store, require
from lexarena.storage.sessions import load_session_state


class GroundTruthRepository:
    def __init__(
        self, principal: Principal, sealed_db: MongoDb, app_db: MongoDb, ns: Namespace = ROOT_NAMESPACE
    ) -> None:
        self._principal = principal
        self._sealed = ns.collection(sealed_db, CASE_GROUND_TRUTH)
        self._app_db = app_db
        self._ns = ns

    def put(self, truth: CaseGroundTruth) -> None:
        require(self._principal, Store.CASE_GROUND_TRUTH, Op.WRITE)
        self._sealed.replace_one({"_id": truth.id}, truth.to_document(), upsert=True)

    def get(self, case_id: str, *, session_id: str) -> CaseGroundTruth:
        require(self._principal, Store.CASE_GROUND_TRUTH, Op.READ)
        session = load_session_state(self._app_db, self._ns, session_id)
        if session.case_id != case_id:
            raise SealedError(f"session {session_id} is not about case {case_id}")
        if session.state not in UNSEALED_STATES:
            raise SealedError(f"case {case_id} is sealed: session {session_id} is {session.state}")
        doc = self._sealed.find_one({"_id": case_id})
        if doc is None:
            raise NotFoundError(f"ground truth for case {case_id}")
        return CaseGroundTruth.model_validate(doc)
