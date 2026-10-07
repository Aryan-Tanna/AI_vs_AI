"""MongoDB plumbing shared by the repositories: collection names and an optional test namespace."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pymongo.collection import Collection
from pymongo.database import Database

Doc = dict[str, Any]
MongoDb = Database[Doc]

CASES = "cases"
CASE_GROUND_TRUTH = "case_ground_truth"  # in the sealed database only
TRANSCRIPT_TURNS = "transcript_turns"
TURN_PRIVATE = "turn_private"
SESSIONS = "sessions"
LAW_DB = "law_db"
TEMPORAL_OVERLAY = "temporal_overlay"
PREDICATE_REGISTRY = "predicate_registry"


@dataclass(frozen=True)
class Namespace:
    """Prefix for collection names. Empty in real runs; tests use a unique prefix and drop it afterwards."""

    prefix: str = ""

    def collection(self, db: MongoDb, name: str) -> Collection[Doc]:
        return db[f"{self.prefix}{name}"]


ROOT_NAMESPACE = Namespace()
