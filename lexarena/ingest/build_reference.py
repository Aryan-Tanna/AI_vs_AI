"""Build the canonical reference precedent DB (build steps A-D).

  python -m lexarena.ingest.build_reference

Reads the raw nclat_precedents*/ files (read-only), normalises, deduplicates and writes
data/canonical/reference_cases.jsonl plus data/reports/reference_build.md.

Dedup: two records are the same case if (normalised title, decision date) match, or if they share an appeal
number/year pair *and* the decision date (connected appeals decided by one judgment). Union-find over both.
The representative is the longest record; sources and statutes are merged.
"""
import collections
import hashlib
import json
import re
from pathlib import Path

from lexarena.config import ROOT, Settings
from lexarena.ingest.load_raw import load_all
from lexarena.ingest.normalise import appeal_keys, normalise

STOP = re.compile(r"\b(m/s\.?|mr\.?|ms\.?|mrs\.?|shri|ltd|limited|pvt|private|and|anr|ors)\b")


def title_key(title: str) -> str:
    return re.sub(r"[^a-z]", "", STOP.sub("", (title or "").lower()))[:40]


class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


CANONICAL_FIELDS = ["precedent_id", "case_title", "appeal_number", "decision_date", "bench", "forum", "final_order",
                    "operative_order", "statutes_cited", "material_facts", "legal_issues", "ratio_decidendi", "summary",
                    "is_overruled"]


def apply_mapping(rec: dict, mapping: dict, id_field: str) -> dict:
    """Rename raw fields to the canonical names (mapping: canonical -> raw). Unmapped fields keep their name."""
    out = {c: rec.get(mapping.get(c, c)) for c in CANONICAL_FIELDS if rec.get(mapping.get(c, c)) is not None}
    out["precedent_id"] = rec.get(mapping.get("precedent_id", id_field), out.get("precedent_id", ""))
    out["_file"] = rec.get("_file", "")
    return out


def ingest_specs(settings: Settings) -> list[dict]:
    import yaml
    cfg = yaml.safe_load(settings.sources_file.read_text(encoding="utf-8")) if settings.sources_file.exists() else {}
    return (cfg or {}).get("reference_ingest") or [{"name": "nclat_precedents", "glob": "nclat_precedents*/*.jsonl",
                                                     "id_field": "precedent_id", "mapping": {}}]


def build(root: Path = ROOT, specs: list[dict] | None = None) -> tuple[list[dict], dict]:
    specs = specs or ingest_specs(Settings())
    raw, report = [], None
    for spec in specs:
        part, rep = load_all(root, spec["glob"], spec.get("id_field", "precedent_id"))
        raw += [apply_mapping(r, spec.get("mapping") or {}, spec.get("id_field", "precedent_id")) for r in part]
        if report is None:
            report = rep
        else:
            report.files += rep.files
            report.precedent_id_occurrences += rep.precedent_id_occurrences
            report.parsed += rep.parsed
            report.errors += rep.errors
    recs = [normalise(r) for r in raw]
    uf = _UF(len(recs))
    by_key: dict = {}
    for i, r in enumerate(recs):
        keys = [("t", title_key(r["title"]), r["decision_date"])]
        keys += [("a", k, r["decision_date"]) for k in appeal_keys(r["appeal_number"])]
        for k in keys:
            if k in by_key:
                uf.union(i, by_key[k])
            else:
                by_key[k] = i
    clusters: dict[int, list[int]] = collections.defaultdict(list)
    for i in range(len(recs)):
        clusters[uf.find(i)].append(i)

    cases = []
    for members in clusters.values():
        group = [recs[i] for i in members]
        rep = max(group, key=lambda r: len(r["ratio_decidendi"]) + len(r["material_facts"]) + len(r["summary"]))
        member_keys = sorted(f"{title_key(r['title'])}|{r['decision_date']}|{r['appeal_number']}" for r in group)
        uid = "REF-" + hashlib.sha1("\n".join(member_keys).encode("utf-8")).hexdigest()[:10]
        labels = {r["label"] for r in group}
        cases.append({
            **{k: v for k, v in rep.items() if k not in ("precedent_id", "_file")},
            "case_uid": uid,
            "appeal_numbers": sorted({r["appeal_number"] for r in group if r["appeal_number"]}),
            "statutes": sorted({s for r in group for s in r["statutes"]}),
            "statutes_full": sorted({s for r in group for s in r["statutes_full"]}),
            "ibc": any(r["ibc"] for r in group),
            "is_overruled_raw": any(r["is_overruled_raw"] for r in group),
            "label_conflict": len(labels) > 1,
            "source": {"files": sorted({r["_file"].replace(str(root), "").lstrip("\\/") for r in group}),
                       "raw_precedent_ids": sorted({r["precedent_id"] for r in group})},
            "cluster_size": len(group),
        })
    cases.sort(key=lambda c: (c["decision_date"], c["case_uid"]))
    stats = {
        "raw_precedent_id_occurrences": report.precedent_id_occurrences, "parsed": report.parsed,
        "lost": report.lost, "parse_errors": len(report.errors), "unique_cases": len(cases),
        "duplicates_removed": len(recs) - len(cases), "uid_collisions": len(cases) - len({c["case_uid"] for c in cases}),
        "label_conflicts": sum(c["label_conflict"] for c in cases), "ibc_cases": sum(c["ibc"] for c in cases),
        "labels": dict(collections.Counter(c["label"] for c in cases)),
        "years": dict(sorted(collections.Counter(c["decision_date"][:4] for c in cases).items())),
        "errors": report.errors,
    }
    return cases, stats


def main() -> None:
    s = Settings()
    cases, stats = build()
    out = s.data_dir / "canonical" / "reference_cases.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases), encoding="utf-8")
    rep = s.data_dir / "reports" / "reference_build.md"
    rep.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Reference DB build report", "", "Generated by `python -m lexarena.ingest.build_reference`.", ""]
    lines += [f"- {k}: {v}" for k, v in stats.items() if k != "errors"]
    lines += ["", "## Parse errors (re-source manually)", ""]
    lines += [f"- {e['file']} @ {e['offset']}: {e['error']} (resumed at {e['skipped_to']})" for e in stats["errors"]]
    rep.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k != "errors"}, indent=1))
    print("wrote", out, "and", rep)


if __name__ == "__main__":
    main()
