"""Move precedent records listed in data/sealed/dev_overlap_manifest.json out of data/precedents/.

Each matching line is moved verbatim (bytes unchanged) to data/sealed/dev_overlap_precedents.jsonl,
and a provenance log records its source file and line. A line matches only if precedent_id,
decision_date and title text all match a manifest entry. Re-running moves nothing.

Run: python scripts/quarantine_dev_overlap.py [--dry-run]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEALED = ROOT / "data" / "sealed"
MANIFEST = SEALED / "dev_overlap_manifest.json"
OUT = SEALED / "dev_overlap_precedents.jsonl"
LOG = SEALED / "dev_overlap_provenance.jsonl"


def matches(line: str, entry: dict) -> bool:
    return (f'"{entry["precedent_id"]}"' in line
            and entry["decision_date"] in line
            and entry["title_contains"].lower() in line.lower())


def main(dry_run: bool) -> None:
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))["entries"]
    found = {f'{e["precedent_id"]} | {e["title_contains"]}': 0 for e in entries}
    moved, log = [], []
    for path in sorted((ROOT / "data" / "precedents").glob("*/*.jsonl")):
        lines = path.read_bytes().split(b"\n")
        keep = []
        for n, b in enumerate(lines, 1):
            hit = next((e for e in entries if matches(b.decode("utf-8"), e)), None)
            if hit is None:
                keep.append(b)
                continue
            found[f'{hit["precedent_id"]} | {hit["title_contains"]}'] += 1
            moved.append(b.rstrip(b"\r"))
            log.append({"precedent_id": hit["precedent_id"], "relation": hit["relation"], "dev_case": hit["dev_case"],
                        "source_file": path.relative_to(ROOT).as_posix(), "source_line": n})
        if len(keep) != len(lines) and not dry_run:
            path.write_bytes(b"\n".join(keep))
    for k, v in found.items():
        print(f"{v} line(s)  {k}")
    print(f"total lines moved: {len(moved)}{' (dry run)' if dry_run else ''}")
    if moved and not dry_run:
        with OUT.open("ab") as f:
            for b in moved:
                f.write(b + b"\n")
        with LOG.open("a", encoding="utf-8") as f:
            for row in log:
                f.write(json.dumps(row) + "\n")
    missing = [k for k, v in found.items() if v == 0]
    if missing:
        print("NOT FOUND in data/precedents/ (already moved, or manifest error):", missing)


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
