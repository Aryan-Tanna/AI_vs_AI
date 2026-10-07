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
from lexarena.schemas.law import LawRecord, locate_item
from lexarena.schemas.overlay import TemporalOverlayRow
from lexarena.schemas.predicate import PredicateEntry
from lexarena.storage.mongo import LAW_DB, PREDICATE_REGISTRY, ROOT_NAMESPACE, TEMPORAL_OVERLAY, MongoDb, Namespace
from lexarena.storage.policy import Op, Principal, Store, require
from lexarena.storage.temporal import AsOf, StatuteView, resolve_statute, windows_overlap


class OverlayRejectedError(ValueError):
    """An overlay row that may not be stored (not APPROVED, unknown statute, overlapping window)."""


class PredicateRejectedError(ValueError):
    """A predicate that may not be stored (not APPROVED, unknown statute, Law DB item changed)."""


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
    stale_predicates: list[str]


class LawRepository:
    def __init__(self, principal: Principal, db: MongoDb, ns: Namespace = ROOT_NAMESPACE) -> None:
        self._principal = principal
        self._law = ns.collection(db, LAW_DB)
        self._overlay = ns.collection(db, TEMPORAL_OVERLAY)
        self._predicates = ns.collection(db, PREDICATE_REGISTRY)

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
        stale = self._refresh_predicates()
        return LoadResult(inserted, updated, unchanged, len(gone), self.snapshot(), stale)

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

    def put_predicate(self, entry: PredicateEntry) -> None:
        """Store one predicate. Only APPROVED entries whose Law DB item is unchanged since drafting are stored."""
        require(self._principal, Store.PREDICATE_REGISTRY, Op.WRITE)
        if entry.status != "APPROVED":
            raise PredicateRejectedError(f"{entry.predicate_id}: only APPROVED predicates load (status {entry.status})")
        record = self.get_record(entry.statute_id)
        if record is None:
            raise PredicateRejectedError(f"{entry.predicate_id}: statute {entry.statute_id} is not in the Law DB")
        where = locate_item(record, entry.field, entry.item_index, entry.item_hash)
        if where == "MISSING":
            raise PredicateRejectedError(
                f"{entry.predicate_id}: the Law DB item it encodes has changed since drafting; re-draft it"
            )
        stored = entry.model_copy(update={"item_index": where})
        self._predicates.replace_one({"predicate_id": entry.predicate_id}, stored.to_document(), upsert=True)

    def _refresh_predicates(self) -> list[str]:
        """After a Law DB change: follow moved items, mark changed ones STALE, restore ones whose text is back."""
        stale: list[str] = []
        for doc in self._predicates.find({"status": {"$in": ["APPROVED", "STALE"]}}, projection={"_id": False}):
            entry = PredicateEntry.model_validate(doc)
            record = self.get_record(entry.statute_id)
            where = "MISSING" if record is None else locate_item(record, entry.field, entry.item_index, entry.item_hash)
            update: dict[str, object]
            if where == "MISSING":
                update = {"status": "STALE"}
                stale.append(entry.predicate_id)
            else:
                update = {"status": "APPROVED", "item_index": where}
            self._predicates.update_one({"predicate_id": entry.predicate_id}, {"$set": update})
        return sorted(stale)

    # ------------------------------------------------------------ reads

    def get_record(self, statute_id: str) -> LawRecord | None:
        """The stored Law DB record, unchanged. Ingestion and drafting use it; session roles use get_statute."""
        require(self._principal, Store.LAW_DB, Op.READ)
        doc = self._law.find_one({"_id": statute_id})
        return None if doc is None else StoredLawDoc.model_validate(doc).record

    def statute_ids(self) -> set[str]:
        require(self._principal, Store.LAW_DB, Op.READ)
        return {d["_id"] for d in self._law.find({}, projection={"_id": True})}

    def predicates(self, statute_id: str) -> list[PredicateEntry]:
        """APPROVED predicates for a statute; STALE and other statuses are never served."""
        require(self._principal, Store.PREDICATE_REGISTRY, Op.READ)
        found = self._predicates.find({"statute_id": statute_id, "status": "APPROVED"}, projection={"_id": False})
        return sorted(map(PredicateEntry.model_validate, found), key=lambda e: e.predicate_id)

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
        refs = stored.record.intersecting_statute_ids
        known = {d["_id"] for d in self._law.find({"_id": {"$in": refs}}, projection={"_id": True})}
        return resolve_statute(stored.record, rows, as_of, known)
