"""Statute citation -> Law DB ID resolution, shared by precedent ingestion and the retrieval tools.

General rules only (exact, bracketed sub-section, longest Law DB ID prefix, one spelling variant), then the same
rules on the normalised spelling, then on the spelling rewritten by the reviewed alias table (Q-028, D-050).
Every rewrite keeps the section number, so no rule reaches a different section. Unresolved citations are
reported by the callers, never guessed (D-033).
"""

from __future__ import annotations

import re
from pathlib import Path

from lexarena.ingest.law_db import suggest_ids
from lexarena.schemas.statute_alias import StatuteAliasTable


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
