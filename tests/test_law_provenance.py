"""Evidence for Law DB records authored from official text (D-045): every filled field is backed by quotes
that sit verbatim inside that section's own span of a registered source. Synthetic Test Act for the rule
tests; the last test checks every real provenance file in the repo.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lexarena.drafting.sources import SourceRegistry
from lexarena.ingest.law_provenance import PROVENANCE_DIR, check_provenance, load_provenance
from lexarena.schemas.law import LawRecord
from tests.conftest import REPO_ROOT
from tests.test_drafting_sources import make_pdf, meta
from tests.test_law_validation import law_record

TEXT = (
    "98Y. Neighbour provision.-No order shall be made within ten days.\n"
    "99X. Placeholder provision.-(1) A creditor may apply to the Adjudicating Authority.\n"
    "(2) No application shall be filed after thirty days.\n"
    "100Z. Next provision.-Text of the next provision."
)


@pytest.fixture
def registry(tmp_path: Path) -> SourceRegistry:
    reg = SourceRegistry(tmp_path / "src")
    reg.register(make_pdf(TEXT), meta())
    return reg


def record() -> LawRecord:
    raw = law_record("TEST_ACT_SEC_99X", section_title="Placeholder provision")
    raw["diagnostic_checklist"]["statutory_bars"] = ["No application after thirty days."]
    return LawRecord.model_validate(raw)


def provenance(registry: SourceRegistry, **change: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "statute_id": "TEST_ACT_SEC_99X",
        "record_file": "data/law_db/<file>.json",
        "source_id": "TEST_ACT_2001",
        "source_text_sha256": registry.get("TEST_ACT_2001").text_sha256,
        "text_as_of": "2001-01-01",
        "later_amendments_checked": [],
        "section_starts_with": "99X. Placeholder provision.",
        "section_ends_with": "No application shall be filed after thirty days.",
        "authored_by": "<author>",
        "notes": [],
        "evidence": {
            "section_title": ["Placeholder provision"],
            "statutory_summary": ["A creditor may apply to the Adjudicating Authority"],
            "core_judicial_inquiry": ["A creditor may apply"],
            "diagnostic_checklist.statutory_bars[0]": ["No application shall be filed after thirty days"],
        },
    }
    return {**base, **change}


def problems(registry: SourceRegistry, raw: dict[str, Any]) -> list[str]:
    return check_provenance(load_provenance(json.dumps(raw)), record(), registry)


def test_complete_evidence_inside_the_section_passes(registry: SourceRegistry) -> None:
    assert problems(registry, provenance(registry)) == []


def test_quote_from_the_neighbouring_section_is_refused(registry: SourceRegistry) -> None:
    raw = provenance(registry)
    raw["evidence"]["diagnostic_checklist.statutory_bars[0]"] = ["No order shall be made within ten days"]
    assert any("outside the section" in p for p in problems(registry, raw))


def test_every_filled_field_needs_evidence(registry: SourceRegistry) -> None:
    raw = provenance(registry)
    del raw["evidence"]["diagnostic_checklist.statutory_bars[0]"]
    assert any("no evidence for diagnostic_checklist.statutory_bars[0]" in p for p in problems(registry, raw))


def test_evidence_for_a_field_the_record_does_not_have_is_refused(registry: SourceRegistry) -> None:
    raw = provenance(registry)
    raw["evidence"]["diagnostic_checklist.saving_exceptions[0]"] = ["A creditor may apply"]
    assert any("not in the record" in p for p in problems(registry, raw))


def test_changed_source_and_missing_section_are_refused(registry: SourceRegistry) -> None:
    assert any("differs" in p for p in problems(registry, provenance(registry, source_text_sha256="0" * 64)))
    assert any("not found" in p for p in problems(registry, provenance(registry, section_starts_with="77Q. Absent")))


def test_every_real_provenance_file_passes() -> None:
    """The evidence for each authored Law DB record in the repo, checked against the registered sources."""
    folder = REPO_ROOT / PROVENANCE_DIR
    files = sorted(folder.glob("*.json"))
    if not files:
        pytest.skip("no provenance files yet")
    registry = SourceRegistry(REPO_ROOT / "data" / "legal_sources")
    records = {
        r["_id"]: LawRecord.model_validate(r)
        for path in (REPO_ROOT / "data" / "law_db").glob("*.json")
        for r in json.loads(path.read_text(encoding="utf-8"))
    }
    found = {}
    for path in files:
        prov = load_provenance(path.read_text(encoding="utf-8"))
        found[path.name] = check_provenance(prov, records.get(prov.statute_id), registry)
    assert {name: p for name, p in found.items() if p} == {}
