"""The one place pymupdf (untyped) is called, so the rest of the code stays fully typed."""

from __future__ import annotations

import pymupdf


def pdf_pages_text(data: bytes) -> list[str]:
    """Text layer of each page, in page order; empty strings for pages without one (scans are never OCR'd)."""
    doc = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
    try:
        return [str(page.get_text()) for page in doc.pages()]  # type: ignore[no-untyped-call]
    finally:
        doc.close()  # type: ignore[no-untyped-call]


# pymupdf "blocks" tuples: (x0, y0, x1, y1, text, block_no, block_type); block_type 0 is text, 1 an image.
BLOCK_TEXT, BLOCK_TYPE, TEXT_BLOCK = 4, 6, 0  # literal-ok: pymupdf's documented tuple layout


def pdf_pages_blocks(data: bytes, block_mark: str) -> list[str]:
    """Text of each page with the first line of every layout text block prefixed by `block_mark`, so a judgment
    without paragraph numbers can still be split where the PDF's own blocks begin (D-061)."""
    doc = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
    try:
        pages: list[str] = []
        for page in doc.pages():
            out: list[str] = []
            for block in page.get_text("blocks"):  # type: ignore[no-untyped-call]
                if block[BLOCK_TYPE] != TEXT_BLOCK:
                    continue
                lines = [ln for ln in str(block[BLOCK_TEXT]).splitlines() if ln.strip()]
                if lines:
                    out += [block_mark + lines[0], *lines[1:]]
            pages.append("\n".join(out))
        return pages
    finally:
        doc.close()  # type: ignore[no-untyped-call]
