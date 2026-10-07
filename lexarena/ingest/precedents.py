"""Precedent DB preparation and incremental ingestion into Qdrant (BUILD_PLAN Step 4, DATA_FORMATS §2, D-024).

The stored record is never modified: each Qdrant point's payload is the record exactly as in the source, plus
derived fields beside it (`DERIVED_FIELDS`). Point IDs come from `precedent_uid` (D-024), because `precedent_id`
values collide across different cases; colliding IDs are reported, identical copies of one record collapse into
one point, and differing copies of one case are reported (the first, in file order, is kept).

Vectors (D-005): `facts`, one vector per labelled section of `material_facts` except PARTY IDENTITIES, with
sections over the window size split into windows; `ratio`, parts 1 to 3 of `ratio_decidendi`.
Statute citations are normalised to Law DB IDs by general rules only (exact, longest ID the citation starts
with, then a single spelling-variant match), then through the reviewed alias table in data (Q-028, D-049);
everything unresolved is reported (D-033).

Incremental ingestion: `content_hash` (the record) decides re-embedding; `derived_hash` (the derived fields)
refreshes the payload alone, so a Law DB or alias change reaches stored points without re-embedding them.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from qdrant_client import models

from lexarena.embedding import Embedder, token_windows
from lexarena.ingest.json_files import read_json_values
from lexarena.ingest.law_db import suggest_ids
from lexarena.schemas.precedent import PrecedentRecord
from lexarena.schemas.statute_alias import StatuteAliasTable
from lexarena.storage.precedents import FACTS, RATIO, PrecedentRepository

# DATA_FORMATS §2: "Numbered labelled sections: 1. PARTY IDENTITIES: ... 2. COMMERCIAL TRANSACTION: ..."
SECTION = re.compile(r"(?:^|\s)(?P<number>\d+)\.\s+(?P<label>[A-Z][A-Z /&\-]*[A-Z]):\s*")
EXCLUDED_FACT_SECTIONS = frozenset({"PARTY IDENTITIES"})  # documented: names, not facts to search on
RATIO_PARTS_EMBEDDED = 3  # literal-ok: DATA_FORMATS §2 embeds ratio parts 1 to 3; part 4 is case-specific
INGEST_BATCH = 64  # literal-ok: records embedded and upserted per batch (memory, not behaviour)
DERIVED_FIELDS = frozenset(
    {"precedent_uid", "statutes_normalized", "decision_date_ts", "source_file", "content_hash", "derived_hash"}
)
UID_NAMESPACE = uuid.UUID("6f1c0d1e-8a55-4c6f-9d4b-6c2a3e0b7f11")  # literal-ok: fixed namespace for uuid5 point IDs


@dataclass(frozen=True)
class PrecedentSource:
    file: str
    index: int
    raw: Any


@dataclass
class PreparedPoint:
    precedent_uid: str
    point_id: str
    payload: dict[str, Any]
    content_hash: str
    facts_texts: list[str]
    ratio_text: str


class MalformedPrecedent(BaseModel):
    file: str
    index: int
    precedent_id: str | None
    errors: list[str]


class ConflictingCopies(BaseModel):
    precedent_uid: str
    files: list[str]


class PrecedentPrepReport(BaseModel):
    files: int
    records_read: int
    parse_errors: list[str]
    malformed: list[MalformedPrecedent]
    undated: list[str]
    exact_duplicates: int
    conflicting_copies: list[ConflictingCopies]
    ambiguous_precedent_ids: dict[str, int]
    statute_resolution: dict[str, int]
    unresolved_statutes: dict[str, int]
    sections_without_headings: int
    windowed_sections: int
    ratio_over_model_limit: int
    undocumented_fields: dict[str, int]
    points: int
    snapshot: str


@dataclass
class PreparedPrecedents:
    points: list[PreparedPoint]
    report: PrecedentPrepReport
    ids_by_uid: dict[str, str] = field(default_factory=dict)


def _sections(text: str) -> list[tuple[str, str]]:
    found = list(SECTION.finditer(text))
    return [
        (m.group("label").strip(), text[m.end() : found[i + 1].start() if i + 1 < len(found) else len(text)].strip())
        for i, m in enumerate(found)
    ]


def facts_sections(material_facts: str) -> list[str]:
    """`LABEL: text` for each labelled section except the excluded ones; the whole text if there are none."""
    sections = _sections(material_facts)
    if not sections:
        return [material_facts.strip()] if material_facts.strip() else []
    return [f"{label}: {body}" for label, body in sections if label not in EXCLUDED_FACT_SECTIONS and body]


def ratio_text(ratio_decidendi: str) -> str:
    sections = _sections(ratio_decidendi)
    if not sections:
        return ratio_decidendi.strip()
    return " ".join(f"{label}: {body}" for label, body in sections[:RATIO_PARTS_EMBEDDED])


def load_statute_aliases(path: Path) -> StatuteAliasTable:
    return StatuteAliasTable.model_validate_json(path.read_text(encoding="utf-8"))


def missing_alias_targets(table: StatuteAliasTable, known: set[str]) -> list[str]:
    """Alias targets that start no Law DB ID: an alias that can never resolve anything (reported, not fatal)."""
    return sorted(a.law_db_prefix for a in table.aliases if not any(k.startswith(a.law_db_prefix) for k in known))


def normalize_statutes(
    cited: list[str], known: set[str], aliases: StatuteAliasTable | None = None
) -> tuple[list[str], list[str]]:
    """Law DB IDs for the citations (in order, unique) and the citations that resolve to none."""
    found: list[str] = []
    unresolved: list[str] = []
    for item in cited:
        match = resolve_statute_id(item, known, aliases)[0]
        if match is None:
            if item not in unresolved:
                unresolved.append(item)
        elif match not in found:
            found.append(match)
    return found, unresolved


def _spelling_key(cited: str) -> str:
    """Upper case, every run of separators as one underscore, `SECTION`/`SEC.` as `SEC`, brackets kept."""
    key = re.sub(r"[^A-Z0-9()\[\]]+", "_", cited.upper()).strip("_")
    return re.sub(r"(?:^|_)SECTION(?=_)", "_SEC", key).lstrip("_")


def _general_rules(cited: str, known: set[str]) -> tuple[str | None, str]:
    """(Law DB ID, rule used) by general rules only: exact; bracketed sub-section; longest known ID it starts
    with; one spelling variant."""
    if cited in known:
        return cited, "exact"
    # "..._13(2)" may be a Law DB ID written "..._13_2"; otherwise the bracket belongs to the section before it.
    underscored = re.sub(r"[(\[]\s*([0-9A-Za-z]+)\s*[)\]]", r"_\1", cited).upper()
    if underscored != cited.upper() and underscored in known:
        return underscored, "bracket_as_underscore"
    bare = re.split(r"[(\[]", cited, maxsplit=1)[0].rstrip("_ ")
    if bare != cited and bare in known:
        return bare, "bracketed_subsection"
    tokens = bare.split("_")
    for k in range(len(tokens) - 1, 1, -1):
        prefix = "_".join(tokens[:k])
        if prefix in known:
            return prefix, "section_prefix"
    candidates = suggest_ids(bare, known)
    if len(candidates) == 1:
        return candidates[0], "spelling_variant"
    return None, "unresolved"


def resolve_statute_id(cited: str, known: set[str], aliases: StatuteAliasTable | None = None) -> tuple[str | None, str]:
    """The general rules on the citation as written; then on its normalised spelling; then, if an alias applies,
    on the aliased spelling. Every rewrite keeps the section number, so no rule can reach a different section."""
    match, rule = _general_rules(cited, known)
    if match is not None:
        return match, rule
    key = _spelling_key(cited)
    if key != cited:
        match, rule = _general_rules(key, known)
        if match is not None:
            return match, "normalised_spelling"
    rewritten = aliases.rewrite(key) if aliases is not None else None
    if rewritten is not None:
        match, _ = _general_rules(rewritten, known)
        if match is not None:
            return match, "alias"
    return None, "unresolved"


def content_hash(raw: Any) -> str:
    canonical = json.dumps(raw, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def precedent_uid(record: PrecedentRecord) -> str:
    """D-024: `precedent_id` plus a hash of the normalised title and the decision date."""
    title = re.sub(r"[^a-z0-9]", "", record.case_title.lower())
    digest = hashlib.sha256(f"{title}|{record.decision_date}".encode()).hexdigest()[:12]  # literal-ok: uid suffix
    return f"{record.precedent_id}#{digest}"


def snapshot_id(hashes: dict[str, str]) -> str:
    lines = "".join(f"{uid}:{hashes[uid]}\n" for uid in sorted(hashes))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def read_precedent_sources(folder: Path) -> tuple[list[PrecedentSource], list[str]]:
    sources: list[PrecedentSource] = []
    errors: list[str] = []
    for path in sorted(folder.rglob("*.json*")):
        values, problems = read_json_values(path)
        errors += problems
        rel = path.relative_to(folder).as_posix()
        sources += [PrecedentSource(rel, i, v) for i, v in enumerate(values)]
    return sources, errors


def prepare_precedents(
    sources: list[PrecedentSource],
    parse_errors: list[str],
    known_statutes: set[str],
    embedder: Embedder,
    window_tokens: int,
    max_tokens: int | None = None,
    aliases: StatuteAliasTable | None = None,
) -> PreparedPrecedents:
    malformed: list[MalformedPrecedent] = []
    undated: list[str] = []
    by_uid: dict[str, PreparedPoint] = {}
    files_by_uid: dict[str, list[str]] = defaultdict(list)
    conflicting: set[str] = set()
    exact_duplicates = 0
    resolution: Counter[str] = Counter()
    unresolved_counts: Counter[str] = Counter()
    undocumented: Counter[str] = Counter()
    no_headings = windowed = ratio_long = 0
    count: Callable[[str], int] = embedder.count_tokens

    for src in sources:
        try:
            record = PrecedentRecord.model_validate(src.raw)
        except ValidationError as exc:
            pid = src.raw.get("precedent_id") if isinstance(src.raw, dict) else None
            errors = [f"{'.'.join(map(str, e['loc'])) or '<record>'}: {e['msg']}" for e in exc.errors()]
            malformed.append(MalformedPrecedent(file=src.file, index=src.index, precedent_id=pid, errors=errors))
            continue
        day = record.parsed_decision_date()
        if day is None:
            undated.append(record.precedent_id)
            continue
        uid = precedent_uid(record)
        digest = content_hash(src.raw)
        files_by_uid[uid].append(src.file)
        if uid in by_uid:
            if by_uid[uid].content_hash == digest:
                exact_duplicates += 1
            else:
                conflicting.add(uid)
            continue
        for path in record.undocumented_fields():
            undocumented[path] += 1
        statutes, unresolved = normalize_statutes(record.statutes_cited, known_statutes, aliases)
        for cited in record.statutes_cited:
            resolution[resolve_statute_id(cited, known_statutes, aliases)[1]] += 1
        unresolved_counts.update(unresolved)
        if not _sections(record.material_facts):
            no_headings += 1
        facts: list[str] = []
        for section in facts_sections(record.material_facts):
            pieces = token_windows(section, count, window_tokens)
            windowed += len(pieces) > 1
            facts += pieces
        ratio = ratio_text(record.ratio_decidendi)
        if max_tokens is not None and count(ratio) > max_tokens:
            ratio_long += 1
        derived = {
            "precedent_uid": uid,
            "statutes_normalized": statutes,
            "decision_date_ts": f"{day.isoformat()}T00:00:00Z",
            "source_file": src.file,
        }
        # content_hash decides re-embedding (the record changed); derived_hash catches derived fields that change
        # without the record, e.g. when the Law DB or the alias table grows.
        payload = {**src.raw, **derived, "content_hash": digest, "derived_hash": content_hash(derived)}
        by_uid[uid] = PreparedPoint(uid, str(uuid.uuid5(UID_NAMESPACE, uid)), payload, digest, facts, ratio)

    ids: Counter[str] = Counter(p.payload["precedent_id"] for p in by_uid.values())
    points = list(by_uid.values())
    report = PrecedentPrepReport(
        files=len({s.file for s in sources}),
        records_read=len(sources),
        parse_errors=parse_errors,
        malformed=malformed,
        undated=undated,
        exact_duplicates=exact_duplicates,
        conflicting_copies=[ConflictingCopies(precedent_uid=u, files=files_by_uid[u]) for u in sorted(conflicting)],
        ambiguous_precedent_ids={pid: n for pid, n in sorted(ids.items()) if n > 1},
        statute_resolution=dict(resolution),
        unresolved_statutes=dict(unresolved_counts.most_common()),
        sections_without_headings=no_headings,
        windowed_sections=windowed,
        ratio_over_model_limit=ratio_long,
        undocumented_fields=dict(undocumented),
        points=len(points),
        snapshot=snapshot_id({p.precedent_uid: p.content_hash + p.payload["derived_hash"] for p in points}),
    )
    return PreparedPrecedents(points=points, report=report)


@dataclass(frozen=True)
class PrecedentLoadResult:
    inserted: int
    updated: int
    payload_refreshed: int
    unchanged: int
    removed: int
    points: int
    snapshot: str


def ingest_precedents(
    repo: PrecedentRepository, prepared: PreparedPrecedents, embedder: Embedder
) -> PrecedentLoadResult:
    """Make the Qdrant collection equal the prepared points; embed only new or changed records, and refresh the
    payload alone where only derived fields changed."""
    repo.ensure_collection(embedder.dim)
    stored = repo.stored_hashes()
    todo = [p for p in prepared.points if stored.get(p.point_id, (None, None))[0] != p.content_hash]
    stale = [
        p
        for p in prepared.points
        if p.point_id in stored
        and stored[p.point_id][0] == p.content_hash
        and stored[p.point_id][1] != p.payload["derived_hash"]
    ]
    for start in range(0, len(todo), INGEST_BATCH):
        batch = todo[start : start + INGEST_BATCH]
        texts = [t for p in batch for t in p.facts_texts] + [p.ratio_text for p in batch]
        vectors = embedder.embed(texts)
        facts_iter = iter(vectors[: len(vectors) - len(batch)])
        ratio_vectors = vectors[len(vectors) - len(batch) :]
        points = [
            models.PointStruct(
                id=p.point_id,
                vector={FACTS: [next(facts_iter) for _ in p.facts_texts], RATIO: ratio},
                payload=p.payload,
            )
            for p, ratio in zip(batch, ratio_vectors, strict=True)
        ]
        repo.upsert(points)
    for p in stale:
        repo.overwrite_payload(p.point_id, p.payload)
    wanted = {p.point_id for p in prepared.points}
    gone = sorted(set(stored) - wanted)
    repo.delete(gone)
    inserted = sum(p.point_id not in stored for p in todo)
    return PrecedentLoadResult(
        inserted=inserted,
        updated=len(todo) - inserted,
        payload_refreshed=len(stale),
        unchanged=len(prepared.points) - len(todo) - len(stale),
        removed=len(gone),
        points=repo.count(),
        snapshot=prepared.report.snapshot,
    )
