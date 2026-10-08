"""`cases` repository. Session roles get `agent_view()`, which fetches only `agent_view` from MongoDB and
drops `simulation_date` before validation against `AgentCaseView` (which forbids unknown fields, so a
missed field fails loudly instead of reaching a prompt)."""

from __future__ import annotations

from datetime import date

from lexarena.schemas.case import AgentCaseView, Case
from lexarena.storage.errors import NotFoundError
from lexarena.storage.mongo import CASES, ROOT_NAMESPACE, MongoDb, Namespace
from lexarena.storage.policy import Op, Principal, Store, require

PROMPT_HIDDEN_METADATA = ("simulation_date",)


class CaseRepository:
    def __init__(self, principal: Principal, db: MongoDb, ns: Namespace = ROOT_NAMESPACE) -> None:
        self._principal = principal
        self._col = ns.collection(db, CASES)

    def put(self, case: Case) -> None:
        require(self._principal, Store.CASE_FULL, Op.WRITE)
        self._col.replace_one({"_id": case.id}, case.to_document(), upsert=True)

    def get(self, case_id: str) -> Case:
        require(self._principal, Store.CASE_FULL, Op.READ)
        doc = self._col.find_one({"_id": case_id})
        if doc is None:
            raise NotFoundError(f"case {case_id}")
        return Case.model_validate(doc)

    def index(self) -> list[tuple[str, str, date]]:
        """(case_id, split, simulation_date) of every stored case: what the run manager orders a run by (D-073)."""
        require(self._principal, Store.CASE_FULL, Op.READ)
        docs = self._col.find({}, projection={"split": True, "agent_view.metadata.simulation_date": True})
        return [
            (d["_id"], d["split"], date.fromisoformat(d["agent_view"]["metadata"]["simulation_date"])) for d in docs
        ]

    def agent_view(self, case_id: str) -> AgentCaseView:
        require(self._principal, Store.CASE_AGENT_VIEW, Op.READ)
        doc = self._col.find_one({"_id": case_id}, projection={"agent_view": True})
        if doc is None:
            raise NotFoundError(f"case {case_id}")
        view = doc["agent_view"]
        for name in PROMPT_HIDDEN_METADATA:
            view["metadata"].pop(name, None)
        return AgentCaseView.model_validate({**view, "case_id": case_id})
