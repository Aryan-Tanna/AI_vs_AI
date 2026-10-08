"""Experience memories in Qdrant: `lawyer_memory` and `judge_memory`, one point per lesson (ARCHITECTURE §2, §6;
DATA_FORMATS §5; SPEC F; D-077).

The payload is the lesson as stored (`Lesson.to_document()`); the vector embeds its trigger and lesson text, for
deduplication (SPEC F3). Reflection writes, in a sealed process holding the Qdrant write key; sessions read with the
read-only key, so Qdrant itself refuses a write from a session (D-034). Role checks sit on top, from `policy.POLICY`.

`snapshot()` is a content hash of every stored lesson: equal snapshots before and after a case prove nothing was
written (the run manager's FROZEN and EMPTY proof, D-073).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from qdrant_client import QdrantClient, models

from lexarena.schemas.lesson import Lesson, MemoryKind
from lexarena.storage.policy import Op, Principal, Store, require

COLLECTIONS: dict[MemoryKind, str] = {"LAWYER": "lawyer_memory", "JUDGE": "judge_memory"}
STORES: dict[MemoryKind, Store] = {"LAWYER": Store.LAWYER_MEMORY, "JUDGE": Store.JUDGE_MEMORY}
VECTOR = "lesson"
SCROLL_PAGE = 256  # literal-ok: Qdrant scroll page size
POINT_NAMESPACE = uuid.UUID("6f1d2c3a-4b5e-4f60-8a71-9b0c1d2e3f40")  # fixed namespace for lesson point IDs


def point_id(lesson_id: str) -> str:
    return str(uuid.uuid5(POINT_NAMESPACE, lesson_id))


def lesson_text(lesson: Lesson) -> str:
    return f"{lesson.trigger}\n{lesson.lesson}"


class LessonRepository:
    def __init__(self, principal: Principal, client: QdrantClient, kind: MemoryKind, prefix: str = "") -> None:
        self._principal = principal
        self._client = client
        self._kind = kind
        self._store = STORES[kind]
        self._collection = f"{prefix}{COLLECTIONS[kind]}"

    @property
    def kind(self) -> MemoryKind:
        return self._kind

    def ensure_collection(self, dim: int) -> None:
        require(self._principal, self._store, Op.WRITE)
        if not self._client.collection_exists(self._collection):
            self._client.create_collection(
                self._collection,
                vectors_config={VECTOR: models.VectorParams(size=dim, distance=models.Distance.COSINE)},
            )
            for key in ("lesson_type", "party_status", "status", "statute_ids", "error_code"):
                self._client.create_payload_index(self._collection, key, models.PayloadSchemaType.KEYWORD)

    def upsert(self, lesson: Lesson, vector: list[float]) -> None:
        require(self._principal, self._store, Op.WRITE)
        if lesson.memory != self._kind:
            raise ValueError(f"{lesson.lesson_id} belongs in {lesson.memory} memory, not {self._kind}")
        self._client.upsert(
            self._collection,
            points=[
                models.PointStruct(id=point_id(lesson.lesson_id), vector={VECTOR: vector}, payload=lesson.to_document())
            ],
            wait=True,
        )

    def _scroll(self, with_vectors: bool) -> list[Any]:
        if not self._client.collection_exists(self._collection):
            return []
        points: list[Any] = []
        offset = None
        while True:
            page, offset = self._client.scroll(
                self._collection, limit=SCROLL_PAGE, offset=offset, with_payload=True, with_vectors=with_vectors
            )
            points += page
            if offset is None:
                return points

    def all(self) -> list[Lesson]:
        require(self._principal, self._store, Op.READ)
        return sorted((Lesson.model_validate(p.payload) for p in self._scroll(False)), key=lambda x: x.lesson_id)

    def with_vectors(self) -> list[tuple[Lesson, list[float]]]:
        require(self._principal, self._store, Op.READ)
        out = []
        for p in self._scroll(True):
            vector = p.vector[VECTOR] if isinstance(p.vector, dict) else p.vector
            out.append((Lesson.model_validate(p.payload), [float(x) for x in vector]))
        return sorted(out, key=lambda pair: pair[0].lesson_id)

    def snapshot(self) -> str:
        """sha256 over every lesson's canonical JSON, in lesson-ID order."""
        lessons = self.all()
        canonical = "\n".join(json.dumps(x.to_document(), sort_keys=True) for x in lessons)
        return hashlib.sha256(f"{self._kind}\n{canonical}".encode()).hexdigest()
