"""Precedent DB in Qdrant: one point per precedent, named vectors `facts` (multivector, MAX_SIM) and `ratio`
(DATA_FORMATS §2, D-005). Session processes connect with the read-only key, so Qdrant itself refuses their
writes (D-034); the role checks here sit on top of that.

Every search applies the date cut-off and the case's exclusion list inside Qdrant (SPEC B1, B2), so a later
or excluded precedent never reaches the caller.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from qdrant_client import QdrantClient, models

from lexarena.storage.policy import Op, Principal, Store, require

COLLECTION = "precedents"
FACTS, RATIO = "facts", "ratio"
INDEXED_KEYWORDS = ("precedent_id", "precedent_uid", "statutes_normalized")
SCROLL_PAGE = 256  # literal-ok: Qdrant scroll page size


class PrecedentRepository:
    def __init__(self, principal: Principal, client: QdrantClient, collection: str = COLLECTION) -> None:
        self._principal = principal
        self._client = client
        self._collection = collection

    # ------------------------------------------------------------ writes (ingestion only)

    def ensure_collection(self, dim: int) -> None:
        require(self._principal, Store.PRECEDENTS, Op.WRITE)
        if self._client.collection_exists(self._collection):
            return
        self._client.create_collection(
            self._collection,
            vectors_config={
                FACTS: models.VectorParams(
                    size=dim,
                    distance=models.Distance.COSINE,
                    multivector_config=models.MultiVectorConfig(comparator=models.MultiVectorComparator.MAX_SIM),
                ),
                RATIO: models.VectorParams(size=dim, distance=models.Distance.COSINE),
            },
        )
        for key in INDEXED_KEYWORDS:
            self._client.create_payload_index(self._collection, key, models.PayloadSchemaType.KEYWORD)
        self._client.create_payload_index(self._collection, "decision_date_ts", models.PayloadSchemaType.DATETIME)
        self._client.create_payload_index(
            self._collection,
            "material_facts",
            models.TextIndexParams(type=models.TextIndexType.TEXT, tokenizer=models.TokenizerType.WORD, lowercase=True),
        )

    def upsert(self, points: list[models.PointStruct]) -> None:
        require(self._principal, Store.PRECEDENTS, Op.WRITE)
        if points:
            self._client.upsert(self._collection, points=points, wait=True)

    def overwrite_payload(self, point_id: str, payload: dict[str, Any]) -> None:
        """Replace a point's payload, keeping its vectors (derived fields changed, the record did not)."""
        require(self._principal, Store.PRECEDENTS, Op.WRITE)
        self._client.overwrite_payload(self._collection, payload=payload, points=[point_id], wait=True)

    def delete(self, point_ids: list[str]) -> None:
        require(self._principal, Store.PRECEDENTS, Op.WRITE)
        if point_ids:
            self._client.delete(self._collection, points_selector=models.PointIdsList(points=point_ids), wait=True)

    # ------------------------------------------------------------ reads

    def exists(self) -> bool:
        require(self._principal, Store.PRECEDENTS, Op.READ)
        return bool(self._client.collection_exists(self._collection))

    def count(self) -> int:
        require(self._principal, Store.PRECEDENTS, Op.READ)
        return int(self._client.count(self._collection, exact=True).count)

    def _scroll(self, fields: list[str] | bool) -> list[Any]:
        points: list[Any] = []
        offset = None
        while True:
            page, offset = self._client.scroll(
                self._collection, limit=SCROLL_PAGE, offset=offset, with_payload=fields, with_vectors=False
            )
            points += page
            if offset is None:
                return points

    def stored_hashes(self) -> dict[str, tuple[str, str | None]]:
        """point ID -> (content_hash, derived_hash), for incremental ingestion. Points stored before derived_hash
        existed return None for it, so their payload is refreshed once."""
        require(self._principal, Store.PRECEDENTS, Op.READ)
        if not self._client.collection_exists(self._collection):
            return {}
        return {
            str(p.id): (p.payload["content_hash"], p.payload.get("derived_hash"))
            for p in self._scroll(["content_hash", "derived_hash"])
        }

    def all_payloads(self) -> list[dict[str, Any]]:
        require(self._principal, Store.PRECEDENTS, Op.READ)
        return [dict(p.payload or {}) for p in self._scroll(True)]

    def search_ratio(
        self, vector: list[float], *, decided_before: date, exclude_ids: list[str], limit: int
    ) -> list[dict[str, Any]]:
        """Nearest precedents by legal rule, decided strictly before the cut-off and not excluded (SPEC B1, B2)."""
        require(self._principal, Store.PRECEDENTS, Op.READ)
        found = self._client.query_points(
            self._collection,
            query=vector,
            using=RATIO,
            query_filter=cutoff_filter(decided_before, exclude_ids),
            limit=limit,
            with_payload=True,
        )
        return [dict(p.payload or {}) for p in found.points]


def cutoff_filter(decided_before: date, exclude_ids: list[str]) -> models.Filter:
    return models.Filter(
        must=[models.FieldCondition(key="decision_date_ts", range=models.DatetimeRange(lt=decided_before.isoformat()))],
        must_not=[models.FieldCondition(key="precedent_id", match=models.MatchAny(any=exclude_ids))]
        if exclude_ids
        else [],
    )
