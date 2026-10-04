"""Hybrid retrieval over the reference DB with hard leakage filters (CLAUDE.md §4, §8.2).

Filters run *before* ranking, so an excluded case can never appear and the top-k is always full:
- `exclude`: the simulated case's own copies in the reference DB (manifest.overlap_with_reference_db);
- `cutoff`: only authorities decided strictly before the simulated case's NCLAT decision date;
- treatment: the reference DB has only an undated `is_overruled` flag, so `status_as_of` cannot be computed
  yet (authority table, build step J). Such hits are returned with an explicit "treatment unverified" note,
  never silently.
Ranking: reciprocal-rank fusion of BM25 and dense (when built), plus a small boost for matching provisions.
"""
import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from lexarena.retrieval.bm25 import BM25
from lexarena.retrieval.dense import DenseIndex
from lexarena.retrieval.units import Unit, units_for

RRF_K = 60
CANDIDATES = 200


@dataclass
class Hit:
    case_uid: str
    title: str
    decision_date: str
    bench_city: str
    outcome: str
    kind: str
    text: str
    statutes: list[str]
    score: float
    treatment_note: str | None

    def to_dict(self) -> dict:
        return asdict(self)


class ReferenceIndex:
    def __init__(self, cases: list[dict], dense: DenseIndex | None = None, kinds: tuple[str, ...] = ("proposition", "issue", "facts")):
        self.cases = {c["case_uid"]: c for c in cases}
        self.units: list[Unit] = [u for c in cases for u in units_for(c) if u.kind in kinds]
        self.bm25 = BM25([u.text for u in self.units])
        self.dense = dense
        self.unit_date = [dt.date.fromisoformat(self.cases[u.case_uid]["decision_date"]) for u in self.units]

    @classmethod
    def load(cls, reference_path: Path, index_dir: Path | None = None) -> "ReferenceIndex":
        cases = [json.loads(line) for line in reference_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        idx = cls(cases)
        if index_dir is not None:
            idx.dense = DenseIndex.load(index_dir, [u.text for u in idx.units])
        return idx

    def search(self, query: str, *, cutoff: dt.date, exclude: set[str] = frozenset(), provisions: tuple[str, ...] = (),
               k: int = 6, kinds: tuple[str, ...] = ("proposition", "issue")) -> list[Hit]:
        allowed = {i for i, u in enumerate(self.units)
                   if u.kind in kinds and self.unit_date[i] < cutoff and u.case_uid not in exclude}
        if not allowed:
            return []
        fused: dict[int, float] = {}
        bm = sorted(self.bm25.scores(query, allowed).items(), key=lambda x: -x[1])[:CANDIDATES]
        for rank, (i, _) in enumerate(bm):
            fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + rank)
        if self.dense is not None:
            ds = self.dense.scores(query)
            ranked = sorted(allowed, key=lambda i: -ds[i])[:CANDIDATES]
            for rank, i in enumerate(ranked):
                fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + rank)
        want = set(provisions)
        if want:
            for i in fused:
                overlap = len(want & set(self.cases[self.units[i].case_uid]["statutes"]))
                fused[i] += 0.002 * overlap

        best: dict[str, tuple[float, int]] = {}            # one hit per case: its best unit
        for i, sc in fused.items():
            uid = self.units[i].case_uid
            if uid not in best or sc > best[uid][0]:
                best[uid] = (sc, i)
        hits = []
        for uid, (sc, i) in sorted(best.items(), key=lambda x: -x[1][0])[:k]:
            c, u = self.cases[uid], self.units[i]
            hits.append(Hit(uid, c["title"], c["decision_date"], c["bench_city"], c["label"], u.kind, u.text,
                            c["statutes"], round(sc, 5),
                            "Source DB marks this decision as overruled (undated, unverified); check treatment before relying on it"
                            if c.get("is_overruled_raw") else None))
        return hits
