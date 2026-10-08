"""Pseudonyms for every named person and organisation (SPEC A4, I3-9; D-056).

- Fresh per case: letters are drawn from a generator seeded by the config seed and the case's own key, so a case
  re-clerked gets the same pseudonyms, and different cases get different ones (memory cannot learn an entity).
- A pseudonym names only the kind ("Company-K", "Person-B"); the party's legal status is a separate field.
- Replacement runs before any extraction, on the paragraphs the agent-view extractor will read: longest form
  first, whole words, ignoring case, tolerant of full stops and an "M/s" or honorific prefix. Acronyms (all
  capitals) match case-sensitively, so ordinary words are never hit.
- `residual_names` re-reads the result against the original names' distinctive words (not the variant list), so a
  form the variant list missed still shows up as a leak.
"""

from __future__ import annotations

import random
import re
import string
from collections.abc import Iterable

from lexarena.schemas.clerk import AssignedPseudonym, EntityKind, NamedEntity

KIND_WORD: dict[EntityKind, str] = {
    "PERSON": "Person",
    "COMPANY": "Company",
    "BANK": "Bank",
    "AUTHORITY": "Authority",
    "OTHER": "Entity",
}
PREFIX = r"(?:(?:M/s|Messrs|Mr|Mrs|Ms|Shri|Smt|Sri|Dr)\.?\s+)?"
TOKEN = re.compile(r"[A-Za-z0-9&][\w&'-]*")
MIN_ACRONYM = 3  # literal-ok: shorter capital runs (e.g. "RP", "CD") are ordinary abbreviations, not names


def _letters(count: int, rng: random.Random) -> list[str]:
    singles = list(string.ascii_uppercase)
    rng.shuffle(singles)
    out = list(singles)
    while len(out) < count:  # beyond 26 entities: two-letter suffixes, same shuffled order
        out += [a + b for a in singles for b in singles]
    return out[:count]


def assign_pseudonyms(entities: list[NamedEntity], *, case_key: str, seed: int) -> list[AssignedPseudonym]:
    rng = random.Random(f"{seed}:{case_key}")
    letters = _letters(len(entities), rng)
    return [
        AssignedPseudonym(entity=e, pseudonym=f"{KIND_WORD[e.kind]}-{letter}")
        for e, letter in zip(entities, letters, strict=True)
    ]


FUNCTION_WORDS = frozenset({"of", "and", "the", "for", "in", "on", "at", "to", "by", "&"})


def acronym(name: str) -> str:
    """Initials of the capitalised words, skipping function words whatever their case ("Bank Of India" -> "BI")."""
    return "".join(t[0] for t in TOKEN.findall(name) if t[0].isupper() and t.lower() not in FUNCTION_WORDS)


def _is_acronym(form: str) -> bool:
    return form.isupper() and " " not in form and len(form) >= MIN_ACRONYM


def _pattern(form: str) -> re.Pattern[str]:
    if _is_acronym(form):
        return re.compile(rf"(?<![\w-]){re.escape(form)}(?![\w-])")
    tokens = TOKEN.findall(form)
    body = r"\.?,?\s+".join(re.escape(t) for t in tokens)
    # A trailing full stop belongs to the name only when the form ends in one ("Ltd."); otherwise it ends a sentence.
    tail = r"\.?" if form.rstrip().endswith(".") else ""
    return re.compile(rf"(?<![\w-]){PREFIX}{body}{tail}(?![\w-])", re.IGNORECASE)


class Pseudonymizer:
    def __init__(self, assigned: list[AssignedPseudonym], generic_words: Iterable[str]) -> None:
        self._generic = {w.lower() for w in generic_words}
        # A body named only by generic words and with no real acronym ("Committee of Creditors") is a role, not a name:
        # it stays as written. A name of generic words with a real acronym ("National Bank of X", NBX) is kept.
        self.assigned = [
            a
            for a in assigned
            if _distinctive_words(a.entity.name, self._generic) or len(acronym(a.entity.name)) >= MIN_ACRONYM
        ]
        forms: list[tuple[str, str]] = []
        for a in self.assigned:
            names = {a.entity.name, *a.entity.variants}
            initials = acronym(a.entity.name)
            if len(initials) >= MIN_ACRONYM:
                names.add(initials)
            forms += [(f, a.pseudonym) for f in names if TOKEN.search(f)]
        forms.sort(key=lambda fp: -len(fp[0]))  # longest first: a full name before any of its parts
        self._rules = [(_pattern(f), p) for f, p in forms]

    def apply(self, text: str) -> str:
        for pattern, pseudonym in self._rules:
            text = pattern.sub(pseudonym, text)
        return text


def _distinctive_words(name: str, generic: set[str]) -> set[str]:
    return {
        t.lower()
        for t in TOKEN.findall(name)
        if t.lower() not in generic and t.lower() not in FUNCTION_WORDS and len(t) >= MIN_ACRONYM
    }


def residual_names(text: str, entities: list[NamedEntity], generic_words: Iterable[str]) -> list[str]:
    """Capitalised words in `text` that belong to a real name (other than generic words), in order of first
    appearance; acronyms of the names count too. Reads the original names, never the replacement rules."""
    generic = {w.lower() for w in generic_words}
    distinctive = {
        t.lower()
        for e in entities
        for form in (e.name, *e.variants)
        for t in TOKEN.findall(form)
        if t.lower() not in generic and not _is_acronym(t) and len(t) >= MIN_ACRONYM
    }
    acronyms = {f for e in entities for f in (*e.variants, acronym(e.name)) if _is_acronym(f)}
    hits: list[str] = []
    for word in TOKEN.findall(text):
        bare = word.removesuffix("'s")
        found = bare in acronyms or (bare[:1].isupper() and bare.lower() in distinctive)
        if found and bare not in hits:
            hits.append(bare)
    return hits
