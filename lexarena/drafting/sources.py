"""Registered legal source documents, and the mechanical checks a drafted quote must pass (D-041).

Every `source_text` in a side collection must be a verbatim quote from a document registered here: an
official PDF whose sha256 is pinned, with its extracted text pinned beside it. A quote is accepted only if,
after `normalize`, it is a substring of that text. This removes recall as a source of law: a model may only
point at words that are in the document.

`normalize` is the one declared normalisation: Unicode NFKC (ligatures), typographic quotes and dashes to
ASCII, soft hyphens removed, whitespace runs collapsed. A word split by a hyphen at a line break is matched
both joined ("Gov-/ernment" as "Government") and hyphenated ("pre-/existing" as "pre-existing"). Nothing
else is forgiven; a changed word fails.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date
from pathlib import Path

from pydantic import Field

from lexarena.drafting.pdf import pdf_pages_text
from lexarena.schemas.base import NonEmptyStr, StoredModel

REGISTRY_FILE = "registry.json"
FILES_DIR = "files"
JSON_INDENT = 2  # literal-ok: file indentation
_TRANSLATE = str.maketrans(
    {
        "\N{LEFT SINGLE QUOTATION MARK}": "'",
        "\N{RIGHT SINGLE QUOTATION MARK}": "'",
        "\N{LEFT DOUBLE QUOTATION MARK}": '"',
        "\N{RIGHT DOUBLE QUOTATION MARK}": '"',
        "\N{EN DASH}": "-",
        "\N{EM DASH}": "-",
        "\N{SOFT HYPHEN}": None,
    }
)
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
     "december"], start=1)}  # fmt: skip
_MONTH = r"(january|february|march|april|may|june|july|august|september|october|november|december)"
_ORD = r"(?:st|nd|rd|th)?"
_DATE_PATTERNS = (
    (re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b"), ("d", "m", "y")),
    (re.compile(rf"\b(\d{{1,2}}){_ORD}\s+(?:day\s+of\s+)?{_MONTH},?\s+(\d{{4}})\b", re.I), ("d", "M", "y")),
    (re.compile(rf"\b{_MONTH}\s+(\d{{1,2}}){_ORD},?\s+(\d{{4}})\b", re.I), ("M", "d", "y")),
)
_NUMBER = re.compile(r"(?<![\d.])\d[\d,]*(?:\.\d+)?")


class SourceError(ValueError):
    """A document that cannot be registered."""


class SourceIntegrityError(RuntimeError):
    """A registered document's files no longer match their pinned hashes."""


class SourceMeta(StoredModel):
    source_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    title: NonEmptyStr
    issuer: NonEmptyStr
    reference: NonEmptyStr  # e.g. Act number, or S.O. number and date
    issued_on: date
    url: NonEmptyStr


class LegalSource(SourceMeta):
    retrieved_on: date
    file: str
    file_sha256: str
    text_file: str
    text_sha256: str
    page_chars: list[int]


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).translate(_TRANSLATE).split())


_LINE_BREAK_HYPHEN = re.compile(r"-[ \t]*\r?\n[ \t]*")


def source_readings(source_text: str) -> tuple[str, str]:
    """The normalised source with line-break hyphens joined, and with them kept as hyphens."""
    joined = normalize(_LINE_BREAK_HYPHEN.sub("", source_text))
    hyphenated = normalize(_LINE_BREAK_HYPHEN.sub("-", source_text))
    return joined, hyphenated


def find_quote(quote: str, source_text: str) -> tuple[int, int] | None:
    """Span of the normalised quote in a normalised reading of the source, or None if it is not there verbatim."""
    needle = normalize(quote)
    if not needle:
        return None
    for reading in source_readings(source_text):
        start = reading.find(needle)
        if start >= 0:
            return start, start + len(needle)
    return None


def quote_occurrences(quote: str, source_text: str) -> int:
    """How many times the normalised quote occurs in the reading where it occurs most."""
    needle = normalize(quote)
    if not needle:
        return 0
    return max(reading.count(needle) for reading in source_readings(source_text))


PAGE_BREAK = "\f"  # registered texts join pages with a form feed (SourceRegistry.register)


def quote_pages(quote: str, source_text: str) -> set[int]:
    """1-based numbers of the pages whose text contains the normalised quote."""
    needle = normalize(quote)
    if not needle:
        return set()
    return {
        number
        for number, page in enumerate(source_text.split(PAGE_BREAK), start=1)
        if any(needle in reading for reading in source_readings(page))
    }


def quote_context(quote: str, source_text: str, chars: int) -> str:
    """The quote with `chars` characters either side, from the first reading that contains it."""
    needle = normalize(quote)
    for reading in source_readings(source_text):
        start = reading.find(needle)
        if needle and start >= 0:
            return reading[max(0, start - chars) : start + len(needle) + chars]
    return ""


def dates_mentioned(text: str) -> set[date]:
    """Calendar dates written in common Indian legal styles; impossible dates are ignored, never repaired."""
    found: set[date] = set()
    for pattern, order in _DATE_PATTERNS:
        for match in pattern.finditer(normalize(text)):
            parts = dict(zip(order, match.groups(), strict=True))
            month = int(parts["m"]) if "m" in parts else _MONTHS[parts["M"].lower()]
            try:
                found.add(date(int(parts["y"]), month, int(parts["d"])))
            except ValueError:
                continue
    return found


def numbers_mentioned(text: str) -> set[float]:
    """Numbers written in digits, with Indian or international digit grouping. Numbers in words are not read."""
    return {float(m.replace(",", "")) for m in _NUMBER.findall(normalize(text)) if m.strip(",")}


def excerpts(text: str, terms: list[str], window_chars: int, max_excerpts: int) -> list[str]:
    """Windows of the source around each search hit, merged where they overlap, in document order."""
    spans: list[tuple[int, int]] = []
    for term in terms:
        for match in re.finditer(re.escape(term), text):
            spans.append((max(0, match.start() - window_chars), min(len(text), match.end() + window_chars)))
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [text[s:e] for s, e in merged[:max_excerpts]]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SourceRegistry:
    """`<root>/registry.json` plus `<root>/files/<source_id>.pdf` and `.txt`."""

    def __init__(self, root: Path) -> None:
        self._root = root
        path = root / REGISTRY_FILE
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        self._sources = {s.source_id: s for s in map(LegalSource.model_validate, raw)}

    def all(self) -> list[LegalSource]:
        return sorted(self._sources.values(), key=lambda s: (s.issued_on, s.source_id))

    def get(self, source_id: str) -> LegalSource:
        if source_id not in self._sources:
            raise SourceError(f"source {source_id} is not registered")
        return self._sources[source_id]

    def text(self, source_id: str) -> str:
        """The pinned extracted text, after checking both files still match their hashes."""
        source = self.get(source_id)
        pdf = (self._root / source.file).read_bytes()
        text = (self._root / source.text_file).read_bytes()
        if _sha256(pdf) != source.file_sha256 or _sha256(text) != source.text_sha256:
            raise SourceIntegrityError(f"{source_id}: files no longer match the registered hashes")
        return text.decode("utf-8")

    def register(self, pdf: bytes, meta: SourceMeta, retrieved_on: date | None = None) -> LegalSource:
        if meta.source_id in self._sources:
            raise SourceError(f"{meta.source_id} is already registered")
        file_sha = _sha256(pdf)
        same = [s.source_id for s in self._sources.values() if s.file_sha256 == file_sha]
        if same:
            raise SourceError(f"the same file is already registered as {same[0]}")
        pages = pdf_pages_text(pdf)
        if not any(p.strip() for p in pages):
            raise SourceError(f"{meta.source_id}: the PDF has no text layer (scanned image); it cannot be quoted")
        text = PAGE_BREAK.join(pages).encode("utf-8")
        files = self._root / FILES_DIR
        files.mkdir(parents=True, exist_ok=True)
        (files / f"{meta.source_id}.pdf").write_bytes(pdf)
        (files / f"{meta.source_id}.txt").write_bytes(text)
        source = LegalSource(
            **meta.model_dump(),
            retrieved_on=retrieved_on or date.today(),
            file=f"{FILES_DIR}/{meta.source_id}.pdf",
            file_sha256=file_sha,
            text_file=f"{FILES_DIR}/{meta.source_id}.txt",
            text_sha256=_sha256(text),
            page_chars=[len(p.strip()) for p in pages],
        )
        self._sources[source.source_id] = source
        (self._root / REGISTRY_FILE).write_text(
            json.dumps([s.to_document() for s in self.all()], indent=JSON_INDENT, ensure_ascii=False),
            encoding="utf-8",
        )
        return source
