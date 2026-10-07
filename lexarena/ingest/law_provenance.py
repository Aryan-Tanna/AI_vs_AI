"""Evidence for Law DB records authored from official text (D-045).

A Law DB record keeps exactly its frozen format; its evidence lives beside it in
`data/law_db_provenance/<statute_id>.json` (outside `data/law_db/`, so the loader never reads it). The
evidence maps every filled field of the record to quotes, and `check_provenance` verifies mechanically that:

- the source is registered and its text is the version the record was written from;
- the section's own span (from `section_starts_with` to `section_ends_with`) is found once in that text;
- every filled field has at least one quote, and no quote is given for a field the record lacks;
- every quote is verbatim inside the section's span, so nothing comes from a neighbouring provision.

The paraphrase itself (that the field says what the quotes say) is the reviewer's judgment.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import Field

from lexarena.drafting.sources import SourceError, SourceIntegrityError, SourceRegistry, normalize, source_readings
from lexarena.schemas.base import NonEmptyStr, StoredModel
from lexarena.schemas.law import LIST_FIELDS, LawRecord

PROVENANCE_DIR = "data/law_db_provenance"
QUOTE_PREVIEW_CHARS = 60  # literal-ok: characters of a failing quote shown in the message


class AmendmentCheck(StoredModel):
    source_id: NonEmptyStr
    result: NonEmptyStr


class LawProvenance(StoredModel):
    statute_id: NonEmptyStr
    record_file: NonEmptyStr
    source_id: NonEmptyStr
    source_text_sha256: str
    text_as_of: date
    later_amendments_checked: list[AmendmentCheck]
    section_starts_with: NonEmptyStr
    section_ends_with: NonEmptyStr
    authored_by: NonEmptyStr
    notes: list[str]
    evidence: dict[str, list[NonEmptyStr]] = Field(min_length=1)


def load_provenance(text: str) -> LawProvenance:
    return LawProvenance.model_validate_json(text)


def filled_paths(record: LawRecord) -> set[str]:
    """Every field of the record that states something and so needs evidence."""
    paths = {"section_title", "statutory_summary", "core_judicial_inquiry"}
    paths |= {f"intersecting_statute_ids[{i}]" for i in range(len(record.intersecting_statute_ids))}
    for field in LIST_FIELDS:
        items: list[Any] = getattr(record.diagnostic_checklist, field)
        paths |= {f"diagnostic_checklist.{field}[{i}]" for i in range(len(items))}
    if record.diagnostic_checklist.financial_threshold.minimum_amount is not None:
        paths.add("diagnostic_checklist.financial_threshold")
    for key in ("adjudication_window_days", "rectification_window_days"):
        if getattr(record.procedural_timelines, key) is not None:
            paths.add(f"procedural_timelines.{key}")
    return paths


def _section_spans(prov: LawProvenance, text: str) -> list[str] | str:
    """The section's span in each reading of the source, or a problem message."""
    spans = []
    for reading in source_readings(text):
        start_quote, end_quote = normalize(prov.section_starts_with), normalize(prov.section_ends_with)
        if reading.count(start_quote) != 1:
            continue
        start = reading.find(start_quote)
        end = reading.find(end_quote, start)
        if end >= 0:
            spans.append(reading[start : end + len(end_quote)])
    if not spans:
        return "section start not found exactly once, or its end not found after it"
    return spans


def check_provenance(prov: LawProvenance, record: LawRecord | None, registry: SourceRegistry) -> list[str]:
    if record is None:
        return [f"{prov.statute_id}: no such record in the Law DB"]
    problems: list[str] = []
    try:
        source = registry.get(prov.source_id)
        text = registry.text(prov.source_id)
    except (SourceError, SourceIntegrityError) as exc:
        return [str(exc)]
    if source.text_sha256 != prov.source_text_sha256:
        problems.append(f"{prov.source_id}: registered text differs from the version the record was written from")
    for check in prov.later_amendments_checked:
        try:
            registry.get(check.source_id)
        except SourceError:
            problems.append(f"later amendment source {check.source_id} is not registered")
    spans = _section_spans(prov, text)
    if isinstance(spans, str):
        return [*problems, f"{prov.statute_id}: {spans}"]
    needed = filled_paths(record)
    problems += [f"no evidence for {path}" for path in sorted(needed - set(prov.evidence))]
    problems += [
        f"evidence given for {path}, which is not in the record" for path in sorted(set(prov.evidence) - needed)
    ]
    for path, quotes in sorted(prov.evidence.items()):
        for quote in quotes:
            if not any(normalize(quote) in span for span in spans):
                preview = quote[:QUOTE_PREVIEW_CHARS]
                problems.append(
                    f"{path}: quote not found verbatim inside the section ({preview!r}), or outside the section"
                )
    return problems
