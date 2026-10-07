"""One-time repair of the Law DB and precedent source files (your instruction 2026-10-07; D-036).

What it changes, and nothing else:
1. The 14 places where a precedent file is not valid JSON, each fixed by an exact text replacement that
   must match exactly once (listed in STRUCTURAL_FIXES with the reason).
2. `[cite: N]` markers (generation artefacts, Q-008) removed from every string value.
3. One misspelled key `surge_summary` -> `summary` (the documented field; content kept).
4. The exact duplicate Law DB record PMLA_2002_SEC_8 kept once.
5. Every precedent file written as strict JSON Lines (one record per line); four files were JSON arrays
   inside a .jsonl name.

Verification (the script refuses to write if any check fails):
- every file parses with zero errors afterwards;
- every record readable before is present afterwards and identical once markers are removed;
- the only new records are the ones the structural fixes recovered, and they are listed.

Run: .venv/Scripts/python scripts/repair_source_json.py [--write]   (default is a dry run)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from check_formats import read_json_values  # noqa: E402

CITE = re.compile(r"\s*\[cite:[^\]]*\]")
PRECEDENTS = ROOT / "data" / "precedents"
LAW_DB = ROOT / "data" / "law_db"

# (file relative to data/precedents, exact old text, new text, reason)
STRUCTURAL_FIXES: list[tuple[str, str, str, str]] = [
    ("nclat_precedents/nclat_precedents4.jsonl", 'adjudication."}m\n', 'adjudication."}\n', "stray 'm' after a record"),
    ("nclat_precedents2/db2.jsonl", 'disputes[cite: 7]."志\n', 'disputes[cite: 7]."}\n', "stray character where the closing brace belongs"),
    ("nclat_precedents2/db4.jsonl", 'resolution plan[cite: 35]."\n{', 'resolution plan[cite: 35]."}\n{', "missing closing brace"),
    ("nclat_precedents2/db4.jsonl", 'modified the order[cite: 14]."}}', 'modified the order[cite: 14]."}', "extra closing brace"),
    ("nclat_precedents3/db3.jsonl", 'dismissal[cite: 12]." direction: "ALLOW"}', 'dismissal[cite: 12].", "direction": "ALLOW"}', "unquoted key; kept as an undocumented field"),
    ("nclat_precedents3/db3.jsonl", 'was dismissed."}[cite: 11]\n', 'was dismissed."}\n', "marker outside the record"),
    ("nclat_precedents3/db3.jsonl", 'claim admissibility."}[cite: 12]\n', 'claim admissibility."}\n', "marker outside the record"),
    ("nclat_precedents3/db3.jsonl", 'The appeal was dismissed."}[cite: 14]\n', 'The appeal was dismissed."}\n', "marker outside the record"),
    ("nclat_precedents3/db3.jsonl", 'formally determined."}[cite: 15]\n', 'formally determined."}\n', "marker outside the record"),
    ("nclat_precedents3/db3.jsonl", 'right of hearing."}[cite: 17]\n', 'right of hearing."}\n', "marker outside the record"),
    ("nclat_precedents3/db4.jsonl", 'scheme set aside."[cite: 19]}', 'scheme set aside."}', "marker between the last value and the brace"),
    ("nclat_precedents3/db4.jsonl", 'plan consideration."[cite: 20]}', 'plan consideration."}', "marker between the last value and the brace"),
    ("nclat_precedents3/db4.jsonl", 'Managing Director[cite: 16]."}[cite: 16]\n', 'Managing Director[cite: 16]."}\n', "marker outside the record"),
    ("nclat_precedents3/db4.jsonl", 'Section 31(1)[cite: 17]."}[cite: 17]\n', 'Section 31(1)[cite: 17]."}\n', "marker outside the record"),
]  # fmt: skip
RENAMED_KEYS = {"surge_summary": "summary"}


def strip(value: Any) -> Any:
    if isinstance(value, str):
        return CITE.sub("", value)
    if isinstance(value, list):
        return [strip(v) for v in value]
    if isinstance(value, dict):
        return {RENAMED_KEYS.get(k, k): strip(v) for k, v in value.items()}
    return value


def fail(message: str) -> None:
    sys.exit(f"REFUSED: {message}")


def repair_precedents(write: bool) -> None:
    fixes_by_file: dict[str, list[tuple[str, str, str]]] = {}
    for rel, old, new, why in STRUCTURAL_FIXES:
        fixes_by_file.setdefault(rel, []).append((old, new, why))
    totals = {"before": 0, "after": 0, "recovered": 0, "markers": 0}
    for path in sorted(PRECEDENTS.rglob("*.json*")):
        rel = path.relative_to(PRECEDENTS).as_posix()
        text = path.read_text(encoding="utf-8")
        before, _ = read_json_values(path)
        totals["markers"] += len(CITE.findall(text))
        for old, new, why in fixes_by_file.get(rel, []):
            if text.count(old) != 1:
                fail(f"{rel}: expected exactly one match for fix '{why}', found {text.count(old)}")
            text = text.replace(old, new)
        tmp = path.with_suffix(".repair.tmp")
        tmp.write_text(text, encoding="utf-8")
        repaired, errors = read_json_values(tmp)
        tmp.unlink()
        if errors:
            fail(f"{rel} still has parse errors: {errors}")
        after = [strip(r) for r in repaired]
        cleaned_before = [strip(r) for r in before]
        missing = [r.get("precedent_id") for r in cleaned_before if r not in after]
        if missing:
            fail(f"{rel}: records changed beyond marker removal: {missing}")
        # Multiset difference: a recovered record may be an exact copy of one already in the file.
        remaining = Counter(json.dumps(r, sort_keys=True) for r in cleaned_before)
        recovered = []
        for r in after:
            key = json.dumps(r, sort_keys=True)
            if remaining[key]:
                remaining[key] -= 1
            else:
                recovered.append(r)
        for r in recovered:
            copy = " (exact copy of a record already in the file)" if r in cleaned_before else ""
            print(f"  recovered {rel}: {r.get('precedent_id')}{copy}")
        totals["before"] += len(before)
        totals["after"] += len(after)
        totals["recovered"] += len(recovered)
        if write:
            spaced = '{"precedent_id": ' in text[:200]
            seps = (", ", ": ") if spaced else (",", ":")
            lines = [json.dumps(r, ensure_ascii=False, separators=seps) for r in after]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"precedents: {totals}")


def repair_law_db(write: bool) -> None:
    seen: dict[str, Any] = {}
    for path in sorted(LAW_DB.glob("*.json")):
        records = json.loads(path.read_text(encoding="utf-8"))
        kept, dropped, changed = [], [], 0
        for record in records:
            clean = strip(record)
            changed += clean != record
            if clean["_id"] in seen:
                if seen[clean["_id"]] != clean:
                    fail(f"{clean['_id']} appears twice with different content")
                dropped.append(clean["_id"])
                continue
            seen[clean["_id"]] = clean
            kept.append(clean)
        print(f"law_db {path.name}: {len(records)} -> {len(kept)} records, dropped duplicates {dropped}, {changed} edited")
        if write:
            path.write_text(json.dumps(kept, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    repair_precedents(args.write)
    repair_law_db(args.write)
    print("written" if args.write else "dry run: nothing written")


if __name__ == "__main__":
    main()
