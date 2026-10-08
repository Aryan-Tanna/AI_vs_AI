"""D-033: the code is not fitted to the databases it was built with. Your Law DB, precedent DB and dev judgments
are references; they will grow and change. This test reads identifiers from all of them and fails if any
appears in the package, the prompts or the config, so no behaviour can depend on a particular record.

Scripts (one-off data repairs and audits) and tests are exempt: they are about the data by design.
"""

from __future__ import annotations

import json
import re
from itertools import pairwise
from pathlib import Path

import pytest

from lexarena.ingest.json_files import read_json_values
from tests.conftest import REPO_ROOT

SCANNED = [
    *sorted((REPO_ROOT / "lexarena").rglob("*.py")),
    *sorted((REPO_ROOT / "prompts").rglob("*.txt")),
    *sorted((REPO_ROOT / "config").glob("*.yaml")),
]
NAME_STOPWORDS = {"of", "and", "the", "vs", "ltd", "pvt", "anr", "ors", "on", "mr", "india", "limited", "private"}


def _law_ids() -> set[str]:
    ids: set[str] = set()
    for path in (REPO_ROOT / "data" / "law_db").glob("*.json"):
        for record in json.loads(path.read_text(encoding="utf-8")):
            ids.add(record["_id"])
            ids.update(record["intersecting_statute_ids"])
    return ids


def _precedent_ids() -> set[str]:
    ids: set[str] = set()
    for path in (REPO_ROOT / "data" / "precedents").rglob("*.jsonl"):
        values, _ = read_json_values(path)
        ids.update(v["precedent_id"] for v in values if isinstance(v, dict) and "precedent_id" in v)
    return ids


def _dev_party_names() -> set[str]:
    """Two-word name fragments from the dev judgment file names (e.g. 'Anup Dubey')."""
    names: set[str] = set()
    for path in (REPO_ROOT / "data" / "dev").rglob("*"):
        if path.suffix.lower() != ".pdf":
            continue
        title = re.split(r"_on_\d", path.stem)[0]
        for side in re.split(r"_vs_|\s+v(?:s)?\.?\s+", title):
            words = [w for w in re.split(r"[_\s]+", re.sub(r"[^\w\s]", " ", side)) if w]
            words = [w for w in words if w.lower() not in NAME_STOPWORDS and len(w) > 2]
            names.update(f"{a} {b}".lower() for a, b in pairwise(words))
    return names


def _hits(needles: set[str], *, lower: bool) -> list[str]:
    found = []
    for path in SCANNED:
        text = path.read_text(encoding="utf-8")
        hay = text.lower() if lower else text
        # Whole-token match, so an ID never matches inside a longer word.
        shown = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path.name
        found += [
            f"{shown}: {n}"
            for n in sorted(needles)
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])", hay)
        ]
    return found


def test_sources_were_found() -> None:
    assert SCANNED and _law_ids() and _precedent_ids() and _dev_party_names()


def test_no_law_db_identifier_in_code_prompts_or_config() -> None:
    assert _hits(_law_ids(), lower=False) == []


def test_no_precedent_identifier_in_code_prompts_or_config() -> None:
    assert _hits(_precedent_ids(), lower=False) == []


def test_no_dev_party_name_in_code_prompts_or_config() -> None:
    assert _hits(_dev_party_names(), lower=True) == []


@pytest.mark.parametrize("needle", ["IBC_2016_SEC_7", "2020_NCLAT_DEL_502"])
def test_the_scan_catches_a_planted_identifier(tmp_path: Path, needle: str) -> None:
    planted = tmp_path / "planted.py"
    planted.write_text(f'X = "{needle}"\n', encoding="utf-8")
    SCANNED.append(planted)
    try:
        assert _hits({needle}, lower=False) == [f"planted.py: {needle}"]
    finally:
        SCANNED.remove(planted)
