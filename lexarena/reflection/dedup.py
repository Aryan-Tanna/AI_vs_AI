"""Three-step deduplication (SPEC F3; D-077): structured key, then embedding similarity within the key, then a model
asked whether the two are the same, opposite or different. Opposite lessons are never merged: the newer one is kept
and the older one loses confidence. Pure apart from the `compare` callable.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from lexarena.memory.weights import weakened
from lexarena.schemas.config import MemoryConfig
from lexarena.schemas.lesson import Lesson

Relation = str  # SAME | OPPOSITE | DIFFERENT


def key(lesson: Lesson) -> tuple[object, ...]:
    return (
        lesson.lesson_type,
        lesson.memory,
        lesson.party_status,
        tuple(sorted(lesson.statute_ids)),
        lesson.error_code,
    )


def cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else 0.0


@dataclass(frozen=True)
class Placement:
    writes: list[tuple[Lesson, list[float]]]  # lessons to upsert (the new one, a merged one, a weakened one)
    outcome: str  # INSERTED, MERGED into <id>, INSERTED_OPPOSITE to <id>


def place(
    new: Lesson,
    vector: list[float],
    existing: list[tuple[Lesson, list[float]]],
    compare: Callable[[Lesson, Lesson], Relation],
    cfg: MemoryConfig,
) -> Placement:
    same_key = [(x, v) for x, v in existing if key(x) == key(new) and x.status == "ACTIVE"]
    scored = sorted(((cosine(vector, v), x, v) for x, v in same_key), key=lambda t: -t[0])
    if not scored or scored[0][0] < cfg.dedup_embedding_threshold:
        return Placement([(new, vector)], "INSERTED")
    _, old, old_vector = scored[0]
    relation = compare(old, new)
    if relation == "SAME":
        merged = old.model_copy(update={"frequency": old.frequency + 1, "severity": max(old.severity, new.severity)})
        return Placement([(merged, old_vector)], f"MERGED into {old.lesson_id}")
    if relation == "OPPOSITE":
        return Placement([(new, vector), (weakened(old, cfg), old_vector)], f"INSERTED_OPPOSITE to {old.lesson_id}")
    return Placement([(new, vector)], "INSERTED")
