"""Precedent DB in Qdrant: one point per precedent, named vectors `facts` (multivector, MAX_SIM) and `ratio`
(DATA_FORMATS §2, D-005). Session processes connect with the read-only key, so Qdrant itself refuses their
writes (D-034); the role checks here sit on top of that.

Every search applies the date cut-off and the case's exclusion list inside Qdrant (SPEC B1, B2), so a later
or excluded precedent never reaches the caller.
"""

from __future__ import annotations

from typing import Any

from qdrant_client import QdrantClient, models

from lexarena.schemas.retrieval import CaseScope
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
        require(self._principal, Store.PRECEDENTS_UNSCOPED, Op.READ)
        if not self._client.collection_exists(self._collection):
            return {}
        return {
            str(p.id): (p.payload["content_hash"], p.payload.get("derived_hash"))
            for p in self._scroll(["content_hash", "derived_hash"])
        }

    def all_payloads(self, fields: list[str] | None = None) -> list[dict[str, Any]]:
        """Every stored payload (or only `fields` of it, to keep memory small), ignoring any case's cut-off:
        ingestion, clerk and orchestrator only (D-052)."""
        require(self._principal, Store.PRECEDENTS_UNSCOPED, Op.READ)
        return [dict(p.payload or {}) for p in self._scroll(fields if fields is not None else True)]


class ScopedPrecedentReader:
    """The only precedent read path for session roles: bound at construction to one case's `CaseScope`, it applies
    the cut-off (strictly before the case's decision date) and the exclusion list inside Qdrant on every call
    (SPEC B1, B2; D-052). Nothing a caller passes can widen the scope."""

    def __init__(
        self, principal: Principal, client: QdrantClient, scope: CaseScope, collection: str = COLLECTION
    ) -> None:
        require(principal, Store.PRECEDENTS, Op.READ)
        self._principal = principal
        self._client = client
        self._scope = scope
        self._collection = collection

    def _filter(self, extra: list[models.Condition]) -> models.Filter:
        excluded = self._scope.excluded_precedent_ids
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="decision_date_ts", range=models.DatetimeRange(lt=self._scope.decided_before.isoformat())
                ),
                *extra,
            ],
            must_not=[models.FieldCondition(key="precedent_id", match=models.MatchAny(any=excluded))]
            if excluded
            else [],
        )

    def search(
        self, using: str, query: list[float] | list[list[float]], statutes: list[str], limit: int
    ) -> list[tuple[dict[str, Any], float]]:
        """Nearest precedents on the named vector (`facts` takes a list of vectors, `ratio` one vector), optionally
        restricted to precedents citing any of `statutes` (Law DB IDs, SPEC B7)."""
        require(self._principal, Store.PRECEDENTS, Op.READ)
        if using not in (FACTS, RATIO):
            raise ValueError(f"unknown vector {using!r}")
        extra: list[models.Condition] = (
            [models.FieldCondition(key="statutes_normalized", match=models.MatchAny(any=statutes))] if statutes else []
        )
        found = self._client.query_points(
            self._collection,
            query=query,
            using=using,
            query_filter=self._filter(extra),
            limit=limit,
            with_payload=True,
        )
        return [(dict(p.payload or {}), float(p.score)) for p in found.points]

    def get(self, precedent_uid: str) -> dict[str, Any] | None:
        """One precedent by its unique ID, or None if it does not exist or lies outside the scope."""
        require(self._principal, Store.PRECEDENTS, Op.READ)
        page, _ = self._client.scroll(
            self._collection,
            scroll_filter=self._filter(
                [models.FieldCondition(key="precedent_uid", match=models.MatchValue(value=precedent_uid))]
            ),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        return dict(page[0].payload or {}) if page else None
