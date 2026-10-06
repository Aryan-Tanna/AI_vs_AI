"""Rewrite `intersecting_statute_ids` that name an existing Law DB provision in another spelling (Q-022, D-040).

Only references with exactly one suggestion from `suggest_ids` are rewritten (another spelling of the same
section, or a sub-section/clause of a provision the Law DB stores at section level). References to
provisions that are not in the Law DB are left in place: they are reported by `lexarena law validate`,
ignored when related provisions are loaded, and reconnect by themselves once the section is added.

Verification (refuses to write otherwise): same records, same order, and only `intersecting_statute_ids`
changed. A rewrite that duplicates an ID already in the list keeps the first occurrence.

Run: .venv/Scripts/python scripts/fix_law_crossrefs.py [--write]   (default is a dry run)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lexarena.ingest.law_db import read_law_sources, suggest_ids, validate_law_db  # noqa: E402

LAW_DB = ROOT / "data" / "law_db"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    report = validate_law_db(*read_law_sources(LAW_DB))
    if not report.loadable:
        sys.exit("REFUSED: the Law DB has blocking problems; run lexarena law validate")
    known = set(report.records)
    rewrites = {}
    for ref in report.dangling_intersecting:
        found = suggest_ids(ref.missing_id, known)
        if len(found) == 1:
            rewrites[ref.missing_id] = found[0]

    total = 0
    for path in sorted(LAW_DB.glob("*.json")):
        records = json.loads(path.read_text(encoding="utf-8"))
        changed = 0
        for record in records:
            old = record["intersecting_statute_ids"]
            new = list(dict.fromkeys(rewrites.get(i, i) for i in old))
            if new != old:
                record["intersecting_statute_ids"] = new
                changed += 1
        before = json.loads(path.read_text(encoding="utf-8"))
        for a, b in zip(before, records, strict=True):
            if {k: v for k, v in a.items() if k != "intersecting_statute_ids"} != {
                k: v for k, v in b.items() if k != "intersecting_statute_ids"
            }:
                sys.exit(f"REFUSED: {a['_id']} would change beyond intersecting_statute_ids")
        total += changed
        print(f"{path.name}: {changed} records rewritten")
        if args.write and changed:
            path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(rewrites)} distinct IDs rewritten in {total} records")
    print("written" if args.write else "dry run: nothing written")


if __name__ == "__main__":
    main()
