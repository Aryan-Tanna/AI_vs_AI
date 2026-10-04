"""Shared read-only services (law DB, authority registry, reference index), loaded once per process."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from lexarena.config import ROOT, Settings
from lexarena.law.authorities import AuthorityRegistry
from lexarena.law.provisions import LawStore
from lexarena.retrieval.search import ReferenceIndex


@dataclass
class Services:
    law: LawStore
    authorities: AuthorityRegistry
    index: ReferenceIndex | None          # None until `python -m lexarena.ingest.build_reference` has run


@lru_cache(maxsize=4)
def _load(reference_path: Path, index_dir: Path, seed_path: Path, root: Path) -> Services:
    index = ReferenceIndex.load(reference_path, index_dir) if reference_path.exists() else None
    return Services(LawStore.load(root), AuthorityRegistry.load(reference_path, seed_path), index)


def get_services(settings: Settings) -> Services:
    return _load(settings.reference_path, settings.index_dir, settings.data_dir / "seed" / "sc_landmarks.json", ROOT)
