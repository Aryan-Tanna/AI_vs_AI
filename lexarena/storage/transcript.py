"""Published turns (readable by both lawyers, THEMIS and judges) and private turn data (the owning side's
reflection only, after the verdict). Two collections, so no projection can mix them (D-035)."""

from __future__ import annotations

from lexarena.schemas.base import Side
from lexarena.schemas.session import UNSEALED_STATES
from lexarena.schemas.transcript import PrivateTurnData, PublishedTurn
from lexarena.storage.errors import SealedError
from lexarena.storage.mongo import ROOT_NAMESPACE, TRANSCRIPT_TURNS, TURN_PRIVATE, MongoDb, Namespace
from lexarena.storage.policy import Op, Principal, Scope, Store, require
from lexarena.storage.sessions import load_session_state


class TranscriptRepository:
    def __init__(self, principal: Principal, db: MongoDb, ns: Namespace = ROOT_NAMESPACE) -> None:
        self._principal = principal
        self._col = ns.collection(db, TRANSCRIPT_TURNS)

    def publish(self, turn: PublishedTurn) -> None:
        """Insert only: a published turn is never edited (duplicate IDs raise)."""
        require(self._principal, Store.PUBLISHED_TURNS, Op.WRITE)
        self._col.insert_one(turn.to_document())

    def turns(self, session_id: str) -> list[PublishedTurn]:
        require(self._principal, Store.PUBLISHED_TURNS, Op.READ)
        docs = self._col.find({"session_id": session_id}).sort("turn", 1)
        return [PublishedTurn.model_validate(d) for d in docs]


class PrivateTurnRepository:
    def __init__(self, principal: Principal, db: MongoDb, ns: Namespace = ROOT_NAMESPACE) -> None:
        self._principal = principal
        self._db = db
        self._ns = ns
        self._col = ns.collection(db, TURN_PRIVATE)

    def put(self, data: PrivateTurnData) -> None:
        require(self._principal, Store.PRIVATE_TURNS, Op.WRITE, data_side=data.side)
        self._col.replace_one({"_id": data.id, "side": data.side}, data.to_document(), upsert=True)

    def for_side(self, session_id: str, side: Side) -> list[PrivateTurnData]:
        scope = require(self._principal, Store.PRIVATE_TURNS, Op.READ, data_side=side)
        if scope in (Scope.AFTER_VERDICT, Scope.OWN_SIDE_AFTER_VERDICT):
            state = load_session_state(self._db, self._ns, session_id).state
            if state not in UNSEALED_STATES:
                raise SealedError(f"private turn data of session {session_id} is sealed until the verdict ({state})")
        docs = self._col.find({"session_id": session_id, "side": side}).sort("turn", 1)
        return [PrivateTurnData.model_validate(d) for d in docs]
