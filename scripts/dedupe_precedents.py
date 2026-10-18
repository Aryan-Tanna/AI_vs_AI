"""Clean duplicate precedent IDs in data/precedents (owner's instruction 2026-10-19; D-146). Values only: the record
format is untouched (CLAUDE.md §4.5).

Decided on CONTENT, never on the ID or title alone (owner, 2026-10-19). "Text" is the ratio, material facts and
final order, lower-cased with punctuation and spacing collapsed. In file order:
- same ID, text at least SAME_TEXT similar to a kept record with that ID: the same judgment again, dropped;
- same ID, text different: a different document, kept under the next free suffix (`_B`, `_C`, ...), the convention
  the DB already uses (e.g. 2024_NCLAT_DEL_664_B);
- different ID, identical text AND the same title as a kept record: the same judgment under two IDs, dropped, and its
  ID recorded as folded into the kept one; identical text under different titles (connected appeals decided by one
  order) is kept.
Writes the files back in place (git shows every change), plus data/sealed/precedent_id_changes.json mapping each
renamed record's old ID to its new one, which `--apply-exclusions` uses to keep every case's excluded list closed:
a case that excluded an old ID also excludes the new one.

    python scripts/dedupe_precedents.py --dry-run
    python scripts/dedupe_precedents.py
    .venv/Scripts/python scripts/dedupe_precedents.py --apply-exclusions
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import string
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "precedents"
CHANGES = ROOT / "data" / "sealed" / "precedent_id_changes.json"
SAME_TEXT = 0.9  # literal-ok: data-cleaning cut-off; measured pairs fall at 0.85-1.0 (same judgment) or below 0.31
TEXT_FIELDS = ("ratio_decidendi", "material_facts", "final_order")


def norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def text_of(rec: dict) -> str:
    return norm_title(" ".join(str(rec.get(k, "")) for k in TEXT_FIELDS))


def same_text(a: dict, b: dict) -> bool:
    ta, tb = text_of(a), text_of(b)
    return ta == tb or difflib.SequenceMatcher(None, ta, tb).ratio() >= SAME_TEXT


def clean(dry_run: bool) -> dict[str, list[str]]:
    files = sorted(SRC.glob("**/*.jsonl"))
    rows: list[tuple[Path, str]] = []
    for f in files:
        rows += [(f, line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    all_ids = {json.loads(line)["precedent_id"] for _, line in rows}
    seen: dict[str, list[dict]] = defaultdict(list)  # id -> kept records under it (original records)
    by_text: dict[tuple[str, str], str] = {}  # (text, title) of a kept record -> the ID it is kept under
    out: dict[Path, list[str]] = defaultdict(list)
    renamed: dict[str, list[str]] = defaultdict(list)
    folded: dict[str, str] = {}  # dropped ID -> the ID of the same judgment that was kept
    dropped_same = dropped_cross = 0
    for f, line in rows:
        rec = json.loads(line)
        pid = rec["precedent_id"]
        kept = seen[pid]
        if any(same_text(k, rec) for k in kept):
            dropped_same += 1
            continue
        tkey = (text_of(rec), norm_title(rec.get("case_title", "")))
        if not kept and tkey in by_text and by_text[tkey] != pid:
            folded[pid] = by_text[tkey]
            dropped_cross += 1
            continue
        kept.append(rec)
        if len(kept) > 1:
            suffix = next(
                s for s in string.ascii_uppercase[1:] if f"{pid}_{s}" not in all_ids and f"{pid}_{s}" not in seen
            )
            new = f"{pid}_{suffix}"
            renamed[pid].append(new)
            seen[new].append(rec)
            rec = {**rec, "precedent_id": new}
        by_text.setdefault(tkey, rec["precedent_id"])
        out[f].append(json.dumps(rec, ensure_ascii=False))
    total = sum(len(v) for v in out.values())
    print(f"{len(rows)} records in -> {total} out: {dropped_same} copies of the same judgment under one ID dropped, "
          f"{dropped_cross} same judgment under a second ID dropped, {sum(len(v) for v in renamed.values())} "
          f"different documents given their own ID")
    for old, kept_id in folded.items():
        print(f"  folded {old} into {kept_id}")
    for pid, news in list(renamed.items())[:10]:
        print(f"  {pid} -> also {news}")
    if not dry_run:
        for f in files:
            f.write_text("\n".join(out.get(f, [])) + "\n", encoding="utf-8")
        CHANGES.parent.mkdir(parents=True, exist_ok=True)
        CHANGES.write_text(json.dumps({"renamed": renamed, "folded": folded}, indent=1, sort_keys=True), encoding="utf-8")
        print(f"written; ID changes in {CHANGES.relative_to(ROOT)}")
    return renamed


def apply_exclusions() -> int:
    """Every stored case that excluded an old ID now also excludes the IDs split off it."""
    sys.path.insert(0, str(ROOT))
    from lexarena.app import DEFAULT_ENV_FILE, SEALED_ENV_FILE
    from lexarena.storage.factory import SealedProcess

    changes = json.loads(CHANGES.read_text(encoding="utf-8"))
    renamed: dict[str, list[str]] = changes["renamed"]
    folded: dict[str, str] = changes["folded"]
    with SealedProcess.from_env_files([DEFAULT_ENV_FILE, SEALED_ENV_FILE]) as proc:
        cases = proc.clerk().cases
        for case_id in sorted(row[0] for row in cases.index()):
            case = cases.get(case_id)
            excluded = list(case.build.excluded_precedent_ids)
            extra = {n for pid in excluded for n in renamed.get(pid, [])}
            extra |= {folded[pid] for pid in excluded if pid in folded}
            extra = sorted(extra - set(excluded))
            if extra:
                build = case.build.model_copy(update={"excluded_precedent_ids": sorted({*excluded, *extra})})
                cases.put(case.model_copy(update={"build": build}))
                print(f"{case_id}: also excludes {extra}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply-exclusions", action="store_true")
    a = ap.parse_args()
    if a.apply_exclusions:
        raise SystemExit(apply_exclusions())
    clean(a.dry_run)
