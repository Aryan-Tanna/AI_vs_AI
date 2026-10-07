"""The labelled-section structure of precedent text (DATA_FORMATS §2), shared by ingestion and retrieval.

`material_facts` and `ratio_decidendi` are written as numbered labelled sections ("1. ABSTRACT LEGAL RULE: ...").
Parsing follows that documented format only, never particular records (D-033).
"""

from __future__ import annotations

import re

# DATA_FORMATS §2: "Numbered labelled sections: 1. PARTY IDENTITIES: ... 2. COMMERCIAL TRANSACTION: ..."
SECTION = re.compile(r"(?:^|\s)(?P<number>\d+)\.\s+(?P<label>[A-Z][A-Z /&\-]*[A-Z]):\s*")
EXCLUDED_FACT_SECTIONS = frozenset({"PARTY IDENTITIES"})  # documented: names, not facts to search on
RATIO_PARTS_EMBEDDED = 3  # literal-ok: DATA_FORMATS §2 embeds ratio parts 1 to 3; part 4 is case-specific


def sections(text: str) -> list[tuple[str, str]]:
    """(label, body) for each numbered labelled section, in order."""
    found = list(SECTION.finditer(text))
    return [
        (m.group("label").strip(), text[m.end() : found[i + 1].start() if i + 1 < len(found) else len(text)].strip())
        for i, m in enumerate(found)
    ]


def facts_sections(material_facts: str) -> list[str]:
    """`LABEL: text` for each labelled section except the excluded ones; the whole text if there are none."""
    found = sections(material_facts)
    if not found:
        return [material_facts.strip()] if material_facts.strip() else []
    return [f"{label}: {body}" for label, body in found if label not in EXCLUDED_FACT_SECTIONS and body]


def ratio_parts(ratio_decidendi: str) -> list[str]:
    """`LABEL: text` for ratio parts 1 to 3 (the general rule); the whole text if it has no labelled sections."""
    found = sections(ratio_decidendi)
    if not found:
        return [ratio_decidendi.strip()] if ratio_decidendi.strip() else []
    return [f"{label}: {body}" for label, body in found[:RATIO_PARTS_EMBEDDED] if body]


def ratio_text(ratio_decidendi: str) -> str:
    """Ratio parts 1 to 3 as one passage (the `ratio` vector's text)."""
    found = sections(ratio_decidendi)
    if not found:
        return ratio_decidendi.strip()
    return " ".join(f"{label}: {body}" for label, body in found[:RATIO_PARTS_EMBEDDED])


def core_rule(ratio_decidendi: str) -> str:
    """Ratio part 1 (ABSTRACT LEGAL RULE in the documented format): the precedent's rule in one passage."""
    parts = ratio_parts(ratio_decidendi)
    return parts[0] if parts else ""
