"""Robust loader for the raw reference precedent files (CLAUDE.md §7.1, build step A).

The files are not valid JSONL: JSON arrays, pretty-printed arrays, several records glued on one line, broken
delimiters. `raw_decode` walks the text; on a parse error a second pass jumps to the next `{"precedent_id"`
instead of the next line, which recovers records that follow a broken one.
"""
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path


def record_start(id_field: str) -> re.Pattern:
    return re.compile(r'\{\s*"' + re.escape(id_field) + r'"')


SKIP = " \t\r\n,[]"


@dataclass
class LoadReport:
    files: int = 0
    precedent_id_occurrences: int = 0
    parsed: int = 0
    errors: list[dict] = field(default_factory=list)

    @property
    def lost(self) -> int:
        return self.precedent_id_occurrences - self.parsed


def iter_raw_records(path: Path, report: LoadReport | None = None, id_field: str = "precedent_id") -> Iterator[dict]:
    txt = path.read_text(encoding="utf-8")
    dec, i, n = json.JSONDecoder(), 0, len(txt)
    if report is not None:
        report.files += 1
        report.precedent_id_occurrences += txt.count(f'"{id_field}"')
    start = record_start(id_field)
    while i < n:
        while i < n and txt[i] in SKIP:
            i += 1
        if i >= n:
            break
        try:
            obj, i = dec.raw_decode(txt, i)
        except json.JSONDecodeError as e:
            nxt = start.search(txt, i + 1)
            if report is not None:
                report.errors.append({"file": str(path), "offset": i, "error": str(e),
                                      "skipped_to": nxt.start() if nxt else None})
            i = nxt.start() if nxt else n
            continue
        for rec in obj if isinstance(obj, list) else [obj]:
            if isinstance(rec, dict):
                rec["_file"] = str(path)
                if report is not None:
                    report.parsed += 1
                yield rec


def load_all(root: Path, pattern: str = "nclat_precedents*/*.jsonl", id_field: str = "precedent_id") -> tuple[list[dict], LoadReport]:
    report = LoadReport()
    recs = [r for f in sorted(root.glob(pattern)) for r in iter_raw_records(f, report, id_field)]
    return recs, report
