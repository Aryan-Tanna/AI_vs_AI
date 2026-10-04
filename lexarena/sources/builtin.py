"""Built-in source types. Each factory takes its config entry (dict) and the project root."""
import datetime as dt
import glob
import json
from pathlib import Path

from lexarena.law.authorities import AuthorityRegistry, AuthorityStatus
from lexarena.law.provisions import LawStore
from lexarena.retrieval.bm25 import BM25
from lexarena.retrieval.search import ReferenceIndex
from lexarena.sources.base import SourceInfo


def _info(cfg: dict, kind: str, **defaults) -> SourceInfo:
    return SourceInfo(name=cfg["name"], kind=kind, court=cfg.get("court", defaults.get("court")),
                      respects_cutoff=cfg.get("respects_cutoff", defaults.get("respects_cutoff", True)),
                      modes=set(cfg.get("modes", ["eval", "live"])), description=cfg.get("description", ""))


def _path(root: Path, p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else root / q


class ReferencePrecedents:
    """Canonical reference DB (output of lexarena.ingest.build_reference): hybrid search + exact-date status."""

    def __init__(self, cfg: dict, root: Path):
        self.info = _info(cfg, "authority", court="NCLAT")
        path = _path(root, cfg["path"])
        self.cases = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []
        self.index = ReferenceIndex(self.cases) if self.cases else None
        if self.index is not None and cfg.get("index_dir"):
            from lexarena.retrieval.dense import DenseIndex
            self.index.dense = DenseIndex.load(_path(root, cfg["index_dir"]), [u.text for u in self.index.units])
        self.registry = AuthorityRegistry(self.cases, [])

    def search(self, query, *, cutoff, exclude, provisions, k):
        if self.index is None:
            return []
        return [h.to_dict() for h in self.index.search(query, cutoff=cutoff, exclude=exclude, provisions=provisions, k=k)]

    def status(self, title, cutoff):
        return self.registry.status(title, cutoff, "NCLAT")


class SeedAuthorities:
    """Curated landmark list (e.g. data/seed/sc_landmarks.json): year-level dates, unverified until checked."""

    def __init__(self, cfg: dict, root: Path):
        self.info = _info(cfg, "authority", court="SC")
        path = _path(root, cfg["path"])
        self.seed = json.loads(path.read_text(encoding="utf-8"))["authorities"] if path.exists() else []
        self.registry = AuthorityRegistry([], self.seed)
        self.bm25 = BM25([f"{s['title']} {s.get('proposition', '')} {' '.join(s.get('provisions', []))}" for s in self.seed]) if self.seed else None

    def search(self, query, *, cutoff, exclude, provisions, k):
        if self.bm25 is None:
            return []
        scores = self.bm25.scores(query + " " + " ".join(provisions))
        hits = []
        for i, sc in sorted(scores.items(), key=lambda x: -x[1]):
            s = self.seed[i]
            if s["year"] >= cutoff.year or s["uid"] in exclude:     # year-level: same-year entries are excluded to be safe
                continue
            hits.append({"case_uid": s["uid"], "title": s["title"], "decision_date": str(s["year"]), "court": self.info.court,
                         "kind": "proposition", "text": s.get("proposition", ""), "score": round(sc, 4),
                         "treatment_note": "Seed entry: year only, unverified"})
            if len(hits) >= k:
                break
        return hits

    def status(self, title, cutoff):
        return self.registry.status(title, cutoff, "SC")


class GenericJsonl:
    """Any JSON/JSONL precedent file, read through a field mapping - no ingest step needed.

    Config: path (glob), fields: {id, title, date, court?, text: [field, ...]}. Dates must be ISO (YYYY-MM-DD).
    """

    def __init__(self, cfg: dict, root: Path):
        self.info = _info(cfg, "authority", court=cfg.get("court"))
        f = cfg["fields"]
        self.records = []
        for p in sorted(glob.glob(str(_path(root, cfg["path"])))):
            txt = Path(p).read_text(encoding="utf-8").strip()
            rows = json.loads(txt) if txt.startswith("[") else [json.loads(x) for x in txt.splitlines() if x.strip()]
            for r in rows:
                try:
                    date = dt.date.fromisoformat(str(r[f["date"]])[:10])
                except (KeyError, ValueError):
                    continue
                text = " ".join(str(r.get(t, "")) for t in f["text"])
                self.records.append({"case_uid": str(r.get(f.get("id", ""), "")) or f"{cfg['name']}-{len(self.records)}",
                                     "title": str(r.get(f["title"], "")), "decision_date": date, "text": text,
                                     "court": r.get(f["court"]) if f.get("court") else self.info.court})
        self.bm25 = BM25([r["text"] for r in self.records]) if self.records else None
        self.registry = AuthorityRegistry([{"case_uid": r["case_uid"], "title": r["title"], "decision_date": r["decision_date"].isoformat(),
                                            "propositions": [r["text"][:600]]} for r in self.records], [])

    def search(self, query, *, cutoff, exclude, provisions, k):
        if self.bm25 is None:
            return []
        allowed = {i for i, r in enumerate(self.records) if r["decision_date"] < cutoff and r["case_uid"] not in exclude}
        ranked = sorted(self.bm25.scores(query + " " + " ".join(provisions), allowed).items(), key=lambda x: -x[1])[:k]
        return [{"case_uid": self.records[i]["case_uid"], "title": self.records[i]["title"],
                 "decision_date": self.records[i]["decision_date"].isoformat(), "court": self.records[i]["court"],
                 "kind": "text", "text": self.records[i]["text"][:800], "score": round(sc, 4), "treatment_note": None}
                for i, sc in ranked]

    def status(self, title, cutoff):
        return self.registry.status(title, cutoff, "NCLAT")


class LawDbJson:
    """The law DB JSON files (law_db/, law2db/ format)."""

    def __init__(self, cfg: dict, root: Path):
        self.info = _info(cfg, "law")
        entries = []
        for pattern in cfg.get("paths", []):
            for p in sorted(glob.glob(str(_path(root, pattern)))):
                entries += json.loads(Path(p).read_text(encoding="utf-8"))
        self.store = LawStore(entries)

    def get(self, provision, as_of):
        return self.store.get(provision, as_of)


BUILTIN_TYPES = {
    "reference_jsonl": ReferencePrecedents,
    "seed_json": SeedAuthorities,
    "generic_jsonl": GenericJsonl,
    "law_db_json": LawDbJson,
}

__all__ = ["BUILTIN_TYPES", "AuthorityStatus"]
