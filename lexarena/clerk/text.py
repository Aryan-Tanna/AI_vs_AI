"""Clerk steps 1-2: clean the judgment text and split it into paragraphs (SPEC H5 rule 1, A5; D-056).

General rules only (D-033), never rules for one source:
- Page furniture: a line that, with its digits ignored, appears on at least `furniture_min_page_share` of the pages
  (and on two pages at least) is a running header or footer, and is removed.
- Encoding: a line with mis-decoded UTF-8 (read as cp1252) is repaired when re-decoding succeeds; replacement
  characters that cannot be repaired are counted. Both are logged as ENCODING_ERROR, never guessed.
- Header: everything before the judgment or order heading (config) is the header; its numbered lines (party
  lists) are not paragraphs. A heading alone on its line wins; only when there is none is a heading merged into a
  line by the PDF layout accepted ("<appeal no.> J U D G M EN T (<date>) ..."). Headings match upper case only.
- Running text: a header line (appeal number, tribunal name) that recurs inside body paragraphs, merged there by
  the PDF layout, is removed from them and flagged.
- Paragraphs: a line starting with the court's paragraph number ("7. ...") opens a paragraph when it is the first
  number seen, the next number, or a small forward jump (the court skipped a number; flagged). Lower numbers and
  big jumps are quotations from other judgments and stay inside the current paragraph. Text before the first
  number is a paragraph of its own. Paragraph IDs P1..Pn are ours and stable; the court's number is kept beside.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from lexarena.schemas.case import ExtractionFlag
from lexarena.schemas.judgment import JudgmentParagraph

# Mis-decoded UTF-8: a lead byte read as cp1252 (A-circumflex, A-tilde, a-circumflex) followed by a byte that
# cp1252 maps to a C1-range or punctuation character. Built from code points to keep the source ASCII.
_LEAD = "".join(map(chr, (0xC2, 0xC3, 0xE2)))  # literal-ok: Unicode code points (encoding repair)
_C1_AND_PUNCTUATION = (*range(0x80, 0xC0), *range(0x2018, 0x203B))  # literal-ok: Unicode code points
_CP1252_EXTRAS = (*range(0x152, 0x179), 0x2C6, 0x2DC, 0x20AC, 0x2122)  # literal-ok: Unicode code points
_TRAIL = "".join(map(chr, (*_C1_AND_PUNCTUATION, *_CP1252_EXTRAS)))
MOJIBAKE = re.compile(f"[{re.escape(_LEAD)}][{re.escape(_TRAIL)}]")
EURO, RUPEE = chr(0x20AC), chr(0x20B9)  # literal-ok: Unicode code points
# A euro sign before a number in Indian lakh grouping (1,54,64,626) is a rupee sign mis-mapped by the PDF's font;
# euro amounts are never grouped that way. Any other euro sign is left as it is.
RUPEE_MISREAD = re.compile(re.escape(EURO) + r"(?=\s?\d{1,3}(?:,\d{2})+,\d{3}(?!\d))")
REPLACEMENT = chr(0xFFFD)  # literal-ok: the Unicode replacement character, an unrecoverable glyph
PARA_START = re.compile(r"^\s*(?P<num>\d{1,3})\.\s+(?P<rest>\S.*)$")
MIN_FURNITURE_PAGES = 2  # literal-ok: a running header needs at least two pages to be seen as repeating


@dataclass(frozen=True)
class Line:
    page: int
    text: str


@dataclass
class CleanedText:
    lines: list[Line]
    removed_furniture: int
    flags: list[ExtractionFlag] = field(default_factory=list)


@dataclass
class SplitText:
    header: str
    paragraphs: list[JudgmentParagraph]
    flags: list[ExtractionFlag] = field(default_factory=list)


# ---------------------------------------------------------------- step 1: clean


def _furniture_key(line: str) -> str:
    return re.sub(r"\d+", "#", " ".join(line.split()))


def _repair(line: str) -> tuple[str, bool]:
    if not MOJIBAKE.search(line):
        return line, False
    try:
        fixed = line.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return line, False
    return fixed, fixed != line


def clean_pages(pages: list[str], furniture_min_page_share: float) -> CleanedText:
    page_lines = [[ln for ln in p.splitlines() if ln.strip()] for p in pages]
    seen_on = Counter(key for lines in page_lines for key in {_furniture_key(ln) for ln in lines})
    needed = max(MIN_FURNITURE_PAGES, math.ceil(furniture_min_page_share * len(pages)))
    furniture = {key for key, n in seen_on.items() if n >= needed} if len(pages) >= MIN_FURNITURE_PAGES else set()

    out: list[Line] = []
    removed = repaired = rupees = 0
    for number, lines in enumerate(page_lines, 1):
        for raw in lines:
            if _furniture_key(raw) in furniture:
                removed += 1
                continue
            text, changed = _repair(raw.strip())
            repaired += changed
            text, rupees_here = RUPEE_MISREAD.subn(RUPEE, text)
            rupees += rupees_here
            out.append(Line(number, text))
    unrepairable = sum(line.text.count(REPLACEMENT) for line in out)
    flags = []
    if repaired or unrepairable or rupees:
        flags.append(
            ExtractionFlag(
                code="ENCODING_ERROR",
                detail=f"repaired {repaired} line(s) of mis-decoded text; {rupees} rupee sign(s) read as euro signs "
                f"before Indian-grouped numbers; unrepairable {unrepairable} character(s)",
                resolution="repaired lines re-decoded as UTF-8; unrepairable characters left as they are for review",
            )
        )
    return CleanedText(lines=out, removed_furniture=removed, flags=flags)


# ---------------------------------------------------------------- step 2: header and paragraphs


def _heading_pattern(heading: str) -> re.Pattern[str]:
    """Upper case only, any spacing between letters ("J U D G M EN T"), never inside a longer word."""
    letters = [c for c in heading.upper() if not c.isspace()]
    return re.compile(r"(?<![A-Z])" + r"\s*".join(map(re.escape, letters)) + r"(?![A-Z])")


def _split_header(lines: list[Line], headings: list[str]) -> tuple[list[Line], list[Line]]:
    patterns = [_heading_pattern(h) for h in headings]
    for i, line in enumerate(lines):
        if any(p.fullmatch(line.text.strip()) for p in patterns):
            return lines[:i], lines[i + 1 :]
    for i, line in enumerate(lines):
        found = [m for p in patterns if (m := p.search(line.text))]
        if found:
            first = min(found, key=lambda m: m.start())
            before, after = line.text[: first.start()].strip(), line.text[first.end() :].strip()
            head = [*lines[:i], *([Line(line.page, before)] if before else [])]
            return head, [*([Line(line.page, after)] if after else []), *lines[i + 1 :]]
    return [], list(lines)


def _remove_running_text(
    paragraphs: list[JudgmentParagraph], header_lines: list[Line], min_chars: int
) -> tuple[list[JudgmentParagraph], list[ExtractionFlag]]:
    """A header line (the appeal number, the tribunal's name) that the PDF layout merged into body text, possibly
    across a line break, is running furniture when it recurs at least twice in the body: removed and flagged."""
    removed: list[str] = []
    texts = [p.text for p in paragraphs]
    for candidate in sorted({" ".join(line.text.split()) for line in header_lines}, key=len, reverse=True):
        if len(candidate) < min_chars:
            continue
        pattern = re.compile(r"\s+".join(map(re.escape, candidate.split())))
        if sum(len(pattern.findall(t)) for t in texts) >= MIN_FURNITURE_PAGES:
            texts = [" ".join(pattern.sub(" ", t).split()) for t in texts]
            removed.append(candidate)
    if not removed:
        return paragraphs, []
    flag = ExtractionFlag(
        code="RUNNING_TEXT_REMOVED",
        detail=f"running header text merged into the body was removed: {sorted(removed)}",
        resolution="removed wherever it recurred; the header keeps it",
    )
    return [p.model_copy(update={"text": t}) for p, t in zip(paragraphs, texts, strict=True)], [flag]


def split_paragraphs(
    cleaned: CleanedText, body_start_headings: list[str], max_number_jump: int, running_text_min_chars: int
) -> SplitText:
    header_lines, body = _split_header(cleaned.lines, body_start_headings)
    paragraphs: list[JudgmentParagraph] = []
    flags: list[ExtractionFlag] = []
    current: list[str] = []
    current_page = body[0].page if body else 1
    current_no: str | None = None
    last_no = 0

    def close() -> None:
        if current:
            paragraphs.append(
                JudgmentParagraph(
                    para_id=f"P{len(paragraphs) + 1}", court_no=current_no, page=current_page, text=" ".join(current)
                )
            )

    for line in body:
        m = PARA_START.match(line.text)
        number = int(m["num"]) if m else 0
        if m and (last_no == 0 or last_no < number <= last_no + max_number_jump):
            if last_no and number != last_no + 1:
                flags.append(
                    ExtractionFlag(
                        code="PARAGRAPH_NUMBERING_GAP",
                        detail=f"court paragraph numbers go {last_no} -> {number} (page {line.page})",
                        resolution="followed the court's numbering; the text between them is kept in order",
                    )
                )
            close()
            current, current_no, current_page, last_no = [m["rest"].strip()], m["num"], line.page, number
        else:
            if not current:
                current_page = line.page
            current.append(line.text.strip())
    close()
    paragraphs, running = _remove_running_text(paragraphs, header_lines, running_text_min_chars)
    header = "\n".join(line.text for line in header_lines)
    return SplitText(header=header, paragraphs=paragraphs, flags=flags + running)
