"""Law DB loader (BUILD_PLAN Step 2): validate every record, report every problem, load only a clean source.

Blocking problems (nothing is loaded): unparseable JSON, a record that does not match the frozen format
(DATA_FORMATS §1), or two records with the same `_id`. Reported but not blocking: dangling
`intersecting_statute_ids`, error-code hygiene, self-references, and fields the format does not document.

Dangling references get suggestions from one general rule (`suggest_ids`); nothing is aliased automatically,
because deciding that two IDs mean the same provision is a data decision for the Law DB owner (D-033).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, ValidationError, computed_field

from lexarena.ingest.json_files import read_json_values
from lexarena.schemas.law import LawRecord

if TYPE_CHECKING:
    from lexarena.storage.law import LawRepository, LoadResult

UPPER_TAG = re.compile(r"[A-Z][A-Z0-9_]*")
SUBDIVISION_MARKER = "SUB"  # tokens from here on name a sub-section of the provision before it


class LawDbNotLoadableError(ValueError):
    """The source has blocking problems; the validation report lists them."""


@dataclass(frozen=True)
class LawSource:
    file: str
    index: int
    raw: Any


@dataclass(frozen=True)
class LoadableRecord:
    record: LawRecord
    content_hash: str
    source_file: str


class MalformedRecord(BaseModel):
    file: str
    index: int
    statute_id: str | None
    errors: list[str]


class DuplicateId(BaseModel):
    statute_id: str
    files: list[str]


class DanglingReference(BaseModel):
    missing_id: str
    referenced_by: list[str]
    suggestions: list[str]


class RecordIssue(BaseModel):
    statute_id: str
    issue: str


class LawValidationReport(BaseModel):
    source: str
    files: int
    records_read: int
    valid: int
    parse_errors: list[str]
    malformed: list[MalformedRecord]
    duplicates: list[DuplicateId]
    dangling_intersecting: list[DanglingReference]
    record_issues: list[RecordIssue]
    undocumented_fields: dict[str, list[str]]
    snapshot: str | None
    records: dict[str, LoadableRecord] = Field(default_factory=dict, exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def loadable(self) -> bool:
        return not (self.parse_errors or self.malformed or self.duplicates)


def content_hash(raw: Any) -> str:
    """Hash of a record's content, independent of key order, whitespace and line endings."""
    canonical = json.dumps(raw, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def snapshot_id(hashes: dict[str, str]) -> str:
    """One ID for the whole Law DB, recorded in every session's version stamp (CLAUDE.md §10)."""
    lines = "".join(f"{statute_id}:{hashes[statute_id]}\n" for statute_id in sorted(hashes))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def read_law_sources(folder: Path) -> tuple[list[LawSource], list[str]]:
    sources: list[LawSource] = []
    parse_errors: list[str] = []
    for path in sorted(folder.glob("*.json")):
        values, errors = read_json_values(path)
        parse_errors += errors
        sources += [LawSource(path.name, i, value) for i, value in enumerate(values)]
    return sources, parse_errors


def suggest_ids(missing_id: str, known_ids: set[str]) -> list[str]:
    """Known IDs that contain every token of `missing_id` (up to any sub-section marker) and end the same way.

    Catches another spelling of the same provision (an act-year token left out) and references to a
    sub-section of a known provision. Never matches a different section number, since tokens compare whole.
    """
    tokens = missing_id.split("_")
    if SUBDIVISION_MARKER in tokens[1:]:
        tokens = tokens[: tokens.index(SUBDIVISION_MARKER, 1)]
    wanted = set(tokens)
    return sorted(
        known
        for known in known_ids
        if wanted <= set(known.split("_")) and known.split("_")[-1] == tokens[-1] and known != missing_id
    )


def _record_issues(record: LawRecord) -> list[RecordIssue]:
    issues = []
    codes = record.audit_error_codes
    if not codes:
        issues.append("no audit_error_codes")
    issues += [f"audit_error_code not an uppercase tag: {c!r}" for c in codes if not UPPER_TAG.fullmatch(c)]
    issues += [f"audit_error_code repeated: {c!r}" for c in sorted(set(codes)) if codes.count(c) > 1]
    refs = record.intersecting_statute_ids
    if record.statute_id in refs:
        issues.append("lists itself in intersecting_statute_ids")
    issues += [f"intersecting id repeated: {r!r}" for r in sorted(set(refs)) if refs.count(r) > 1]
    return [RecordIssue(statute_id=record.statute_id, issue=i) for i in issues]


def validate_law_db(sources: list[LawSource], parse_errors: list[str], source: str = "") -> LawValidationReport:
    valid: dict[str, list[LoadableRecord]] = defaultdict(list)
    malformed: list[MalformedRecord] = []
    for src in sources:
        try:
            record = LawRecord.model_validate(src.raw)
        except ValidationError as exc:
            sid = (src.raw.get("_id") or src.raw.get("statute_id")) if isinstance(src.raw, dict) else None
            errors = [f"{'.'.join(str(p) for p in e['loc']) or '<record>'}: {e['msg']}" for e in exc.errors()]
            malformed.append(MalformedRecord(file=src.file, index=src.index, statute_id=sid, errors=errors))
            continue
        valid[record.statute_id].append(LoadableRecord(record, content_hash(src.raw), src.file))

    duplicates = [
        DuplicateId(statute_id=sid, files=[c.source_file for c in copies])
        for sid, copies in sorted(valid.items())
        if len(copies) > 1
    ]
    unique = {sid: copies[0] for sid, copies in valid.items() if len(copies) == 1}
    known = set(valid)

    referenced_by: dict[str, list[str]] = defaultdict(list)
    issues: list[RecordIssue] = []
    undocumented: dict[str, list[str]] = defaultdict(list)
    for sid in sorted(unique):
        record = unique[sid].record
        for ref in dict.fromkeys(record.intersecting_statute_ids):
            if ref not in known:
                referenced_by[ref].append(sid)
        issues += _record_issues(record)
        for path in record.undocumented_fields():
            undocumented[path].append(sid)

    dangling = [
        DanglingReference(missing_id=ref, referenced_by=by, suggestions=suggest_ids(ref, known))
        for ref, by in sorted(referenced_by.items())
    ]
    report = LawValidationReport(
        source=source,
        files=len({s.file for s in sources}),
        records_read=len(sources),
        valid=sum(len(c) for c in valid.values()),
        parse_errors=parse_errors,
        malformed=malformed,
        duplicates=duplicates,
        dangling_intersecting=dangling,
        record_issues=issues,
        undocumented_fields=dict(undocumented),
        snapshot=None,
        records=unique,
    )
    if report.loadable:
        report.snapshot = snapshot_id({sid: r.content_hash for sid, r in unique.items()})
    return report


def load_law_db(repo: LawRepository, report: LawValidationReport) -> LoadResult:
    """Make the stored Law DB equal the validated source: insert, update, remove; unchanged records untouched."""
    if not report.loadable:
        raise LawDbNotLoadableError(
            f"{len(report.parse_errors)} parse errors, {len(report.malformed)} malformed records, "
            f"{len(report.duplicates)} duplicate IDs; nothing loaded (see the validation report)"
        )
    return repo.sync(report.records)
