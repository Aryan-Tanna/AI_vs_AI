"""Leakage scans on agent-visible text (SPEC H0, H5 rules 9 and 12; D-056). Each returns what it found; the clerk
turns findings into extraction flags and never silently drops text.

- `court_voice_hits`: the appellate court speaking in its own voice ("we are of the view", "this Tribunal has
  already held", "the appeal is dismissed"). Markers come from config. A lower forum's outcome is a legitimate
  fact of the procedural history, so plain outcome words are not markers.
- `citation_hits`: case citations ("X v. Y", reporter citations, "(Supra)") and any authority that counsel cited
  (sealed by default, SPEC H0), named by the ground truth.
"""

from __future__ import annotations

import re

CITATION_PATTERNS = (
    re.compile(r"[A-Z][\w.&'-]*(?:\s+[A-Z&][\w.&'-]*)*\s+(?:v\.|vs\.?|versus)\s+[A-Z]"),
    re.compile(r"\(\d{4}\)\s*\d+\s*SCC\b"),
    re.compile(r"\b\d{4}\s+SCC\s+OnLine\b", re.IGNORECASE),
    re.compile(r"\bAIR\s+\d{4}\b"),
    re.compile(r"\(\s*supra\s*\)", re.IGNORECASE),
)


def _squeeze(text: str) -> str:
    return " ".join(text.split()).lower()


def court_voice_hits(text: str, markers: list[str]) -> list[str]:
    hay = _squeeze(text)
    return [m for m in markers if _squeeze(m) in hay]


def citation_hits(text: str, authority_names: list[str]) -> list[str]:
    hits = [m.group(0) for p in CITATION_PATTERNS for m in p.finditer(text)]
    hay = _squeeze(text)
    hits += [name for name in authority_names if _squeeze(name) and _squeeze(name) in hay]
    return hits
