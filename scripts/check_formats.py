"""Validate every Law DB and precedent record against the documented frozen formats (DATA_FORMATS §1-2).

A report, not a fix: nothing is changed, skipped or special-cased (D-033). It answers whether the data
on disk matches the documented format, and where it does not.

Run: .venv/Scripts/python scripts/check_formats.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lexarena.ingest.json_files import read_json_values  # noqa: E402
from lexarena.schemas.law import LawRecord  # noqa: E402
from lexarena.schemas.precedent import PrecedentRecord  # noqa: E402


def _error_kinds(err: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in e['loc'])}: {e['type']}" for e in err.errors()]


def check(model: type[LawRecord] | type[PrecedentRecord], paths: list[Path]) -> dict[str, Any]:
    total, valid = 0, 0
    validation_errors: Counter[str] = Counter()
    issues: Counter[str] = Counter()
    examples: dict[str, str] = {}
    parse_errors: list[str] = []
    for path in paths:
        values, errors = read_json_values(path)
        parse_errors += errors
        for value in values:
            total += 1
            try:
                record = model.model_validate(value)
            except ValidationError as exc:
                validation_errors.update(_error_kinds(exc))
                continue
            valid += 1
            if isinstance(record, PrecedentRecord):
                found = record.format_issues()
            else:
                found = [("undocumented field", path) for path in record.undocumented_fields()]
            for kind, value in found:
                key = f"{kind}: {value}" if kind == "undocumented field" else kind
                issues[key] += 1
                examples.setdefault(key, value)
    return {
        "files": len(paths),
        "parse_errors": parse_errors,
        "records_read": total,
        "valid": valid,
        "invalid": total - valid,
        "validation_errors": dict(validation_errors.most_common()),
        "format_issues_in_valid_records": {k: {"count": n, "example": examples[k]} for k, n in issues.most_common()},
    }


def main() -> None:
    report = {
        "law_db": check(LawRecord, sorted((ROOT / "data" / "law_db").glob("*.json"))),
        "precedents": check(PrecedentRecord, sorted((ROOT / "data" / "precedents").rglob("*.json*"))),
    }
    law_files = sorted((ROOT / "data" / "law_db").glob("*.json"))
    ids = Counter(r.get("_id") for p in law_files for r in read_json_values(p)[0] if isinstance(r, dict))
    report["law_db"]["duplicate_ids"] = sorted(i for i, n in ids.items() if n > 1)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
