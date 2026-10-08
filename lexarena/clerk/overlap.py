"""Overlap with the precedent DB and the memorisation verdict (SPEC A4, B1; D-019, D-020, D-056).

`find_overlaps` lists precedents that concern the case being clerked: the same parties or the same corporate debtor
(two distinctive words of one party's name in the precedent's title), or the same appeal number together with any
distinctive party word. Every match goes into the case's `excluded_precedent_ids`: over-exclusion is the safe
direction, and each match is listed with its reason for the owner's review. A shared appeal number alone is not a
match, since numbers recur across benches and kinds of case.

`probe_identified` reads the lawyer model's answer to "which case is this?": it counts as identified only if the
answer names a real party (distinctive words) or the real appeal number.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from lexarena.clerk.names import TOKEN
from lexarena.schemas.clerk import NamedEntity

NUMBER_OF_YEAR = re.compile(r"\bNos?\.?\s*(\d{1,6})\s*(?:of|/)\s*((?:19|20)\d{2})\b", re.IGNORECASE)
NUMBER_SLASH_YEAR = re.compile(r"(?<![\d/])(\d{1,6})\s*/\s*((?:19|20)\d{2})\b")
MIN_DISTINCTIVE = 2  # literal-ok: two distinctive words of one name make a party match (one recurs too often)
MIN_WORD = 3  # literal-ok: shorter words are initials or suffixes, not names


@dataclass(frozen=True)
class Overlap:
    precedent_id: str
    precedent_uid: str
    case_title: str
    reason: str


def appeal_numbers(text: str) -> set[tuple[str, str]]:
    return {(n.lstrip("0") or "0", y) for n, y in NUMBER_OF_YEAR.findall(text) + NUMBER_SLASH_YEAR.findall(text)}


def _distinctive(name: str, generic: set[str]) -> set[str]:
    return {t.lower() for t in TOKEN.findall(name) if len(t) >= MIN_WORD and t.lower() not in generic}


def _words(text: str) -> set[str]:
    return {t.lower() for t in TOKEN.findall(text)}


def find_overlaps(
    payloads: Iterable[dict[str, Any]],
    parties: list[NamedEntity],
    *,
    case_numbers: set[tuple[str, str]],
    generic_words: Iterable[str],
) -> list[Overlap]:
    generic = {w.lower() for w in generic_words}
    names = [
        (p.name, _distinctive(p.name, generic) | {w for v in p.variants for w in _distinctive(v, generic)})
        for p in parties
        if p.cause_title_role
    ]
    found: list[Overlap] = []
    for pl in payloads:
        title = _words(pl.get("case_title", ""))
        shared = {name: words & title for name, words in names}
        party_hit = next(((n, w) for n, w in shared.items() if len(w) >= MIN_DISTINCTIVE), None)
        number_hit = appeal_numbers(pl.get("appeal_number", "")) & case_numbers
        if party_hit:
            reason = f"party {party_hit[0]!r} in the title (words {sorted(party_hit[1])})"
        elif number_hit and any(shared.values()):
            reason = f"same appeal number {sorted(number_hit)} and a party word in the title"
        else:
            continue
        found.append(Overlap(pl["precedent_id"], pl["precedent_uid"], pl.get("case_title", ""), reason))
    return found


def probe_identified(
    answer: str, parties: list[NamedEntity], case_numbers: set[tuple[str, str]], generic_words: Iterable[str]
) -> bool:
    generic = {w.lower() for w in generic_words}
    words = _words(answer)
    named = any(
        len(_distinctive(p.name, generic) & words) >= min(MIN_DISTINCTIVE, len(_distinctive(p.name, generic)))
        and _distinctive(p.name, generic)
        for p in parties
    )
    return named or bool(appeal_numbers(answer) & case_numbers)
