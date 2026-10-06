"""Law DB and `temporal_overlay` repository.

Stored Law DB documents wrap the frozen record unchanged: `{_id, record, content_hash, source_file}`
(derived fields beside the record, never inside it; non-negotiable 5). Only the ingestion role writes;
every session role reads through `get_statute`, which applies APPROVED overlay rows for the case's dates.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field

from lexarena.ingest.law_db import LoadableRecord, snapshot_id
from lexarena.schemas.base import NonEmptyStr, StoredModel
from lexarena.schemas.law import LawRecord
from lexarena.schemas.overlay import TemporalOverlayRow
from lexarena.storage.mongo import LAW_DB, ROOT_NAMESPACE, TEMPORAL_OVERLAY, MongoDb, Namespace
from lexarena.storage.policy import Op, Principal, Store, require
from lexarena.storage.temporal import AsOf, StatuteView, resolve_statute, windows_overlap


class OverlayRejectedError(ValueError):
    """An overlay row that may not be stored (not APPROVED, unknown statute, overlapping window)."""


class StoredLawDoc(StoredModel):
    id: NonEmptyStr = Field(alias="_id")
    record: LawRecord
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_file: NonEmptyStr


@dataclass(frozen=True)
class LoadResult:
    inserted: int
    updated: int
    unchanged: int
    removed: int
    snapshot: str


class LawRepository:
    def __init__(self, principal: Principal, db: MongoDb, ns: Namespace = ROOT_NAMESPACE) -> None:
        self._principal = principal
        self._law = ns.collection(db, LAW_DB)
        self._overlay = ns.collection(db, TEMPORAL_OVERLAY)

    # ------------------------------------------------------------ writes (ingestion only)

    def sync(self, records: dict[str, LoadableRecord]) -> LoadResult:
        """Make the stored Law DB equal `records`. Unchanged documents (same content hash) are not rewritten."""
        require(self._principal, Store.LAW_DB, Op.WRITE)
        stored = {d["_id"]: d["content_hash"] for d in self._law.find({}, projection={"content_hash": True})}
        inserted = updated = unchanged = 0
        for statute_id, item in records.items():
            if stored.get(statute_id) == item.content_hash:
                unchanged += 1
                continue
            doc = StoredLawDoc(
                id=statute_id, record=item.record, content_hash=item.content_hash, source_file=item.source_file
            )
            self._law.replace_one({"_id": statute_id}, doc.to_document(), upsert=True)
            if statute_id in stored:
                updated += 1
            else:
                inserted += 1
        gone = sorted(set(stored) - set(records))
        if gone:
            self._law.delete_many({"_id": {"$in": gone}})
        return LoadResult(inserted, updated, unchanged, len(gone), self.snapshot())

    def put_overlay(self, row: TemporalOverlayRow) -> None:
        """Store one overlay row. Only APPROVED rows are stored (non-negotiable 8); drafts live in review/."""
        require(self._principal, Store.TEMPORAL_OVERLAY, Op.WRITE)
        if row.status != "APPROVED":
            raise OverlayRejectedError(f"{row.overlay_id}: only APPROVED rows load (status {row.status})")
        if self._law.count_documents({"_id": row.statute_id}, limit=1) == 0:
            raise OverlayRejectedError(f"{row.overlay_id}: statute {row.statute_id} is not in the Law DB")
        same_slot = {
            "statute_id": row.statute_id,
            "parameter": row.parameter,
            "keyed_on": row.keyed_on,
            "overlay_id": {"$ne": row.overlay_id},
        }
        for other in map(TemporalOverlayRow.model_validate, self._overlay.find(same_slot, projection={"_id": False})):
            if windows_overlap(row, other):
                raise OverlayRejectedError(
                    f"{row.overlay_id}: overlaps {other.overlay_id} for {row.parameter} keyed on {row.keyed_on}"
                )
        self._overlay.replace_one({"overlay_id": row.overlay_id}, row.to_document(), upsert=True)

    # ------------------------------------------------------------ reads

    def snapshot(self) -> str:
        require(self._principal, Store.LAW_DB, Op.READ)
        hashes = {d["_id"]: d["content_hash"] for d in self._law.find({}, projection={"content_hash": True})}
        return snapshot_id(hashes)

    def get_statute(self, statute_id: str, as_of: AsOf) -> StatuteView | None:
        """The provision as it applies on the case's dates, or None if unknown or not in force (indistinguishable)."""
        require(self._principal, Store.LAW_DB, Op.READ)
        require(self._principal, Store.TEMPORAL_OVERLAY, Op.READ)
        doc = self._law.find_one({"_id": statute_id})
        if doc is None:
            return None
        stored = StoredLawDoc.model_validate(doc)
        rows = [
            TemporalOverlayRow.model_validate(r)
            for r in self._overlay.find({"statute_id": statute_id, "status": "APPROVED"}, projection={"_id": False})
        ]
        return resolve_statute(stored.record, rows, as_of)
